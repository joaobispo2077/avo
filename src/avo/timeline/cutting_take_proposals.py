"""Discover source retakes and propose complete removals using bound evidence."""

import re
from copy import deepcopy
from fractions import Fraction

from .contracts import content_hash
from .cutting_contracts import occurrence_id, source_interval
from .cutting_retakes import group_retakes, select_retake


def _segment_range(segment: dict) -> dict:
    return {
        "sourceId": segment["sourceId"],
        "startTicks": segment["in"]["ticks"],
        "endTicksExclusive": segment["out"]["ticks"],
        "timebase": segment["in"]["timebase"],
    }


def _word_chunks(words: list[dict]) -> list[list[dict]]:
    chunks, current = [], []
    for word in words:
        if current and (
            float(word["start"]) - float(current[-1]["end"]) >= 0.25
            or str(current[-1]["text"]).rstrip().endswith((".", "?", "!"))
        ):
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def _search_take(chunk: list[dict], segment: dict) -> dict:
    interval = _segment_range(segment)
    basis = Fraction(interval["timebase"]["num"], interval["timebase"]["den"])
    start = Fraction(str(chunk[0]["start"])) / basis
    end = Fraction(str(chunk[-1]["end"])) / basis
    interval["startTicks"] = max(
        interval["startTicks"], start.numerator // start.denominator
    )
    interval["endTicksExclusive"] = min(
        interval["endTicksExclusive"], -(-end.numerator // end.denominator)
    )
    return {
        "takeId": "take-"
        + content_hash(
            {
                "sourceId": interval["sourceId"],
                "wordAnchors": [word["sourceWordIndex"] for word in chunk],
            }
        )[:16],
        "sourceRange": interval,
        "text": " ".join(str(word["text"]) for word in chunk),
        "complete": None,
        "sourceOrder": interval["startTicks"],
        "words": deepcopy(chunk),
        "timingStatus": "search-only-asr",
    }


def _related(left: dict, right: dict) -> bool:
    a = re.findall(r"\w+", left["text"].casefold())
    b = re.findall(r"\w+", right["text"].casefold())
    if not a or not b:
        return False
    distance = (
        source_interval(right["sourceRange"])[1]
        - source_interval(left["sourceRange"])[2]
    )
    if distance > 30:
        return False
    prefix = min(len(a), len(b), 2)
    return a[:prefix] == b[:prefix]


def discover_retake_groups(analysis: dict, segment: dict) -> list[dict]:
    """ASR can locate candidates, never certify their final complete boundaries."""
    words = [
        {
            **word,
            "text": word.get("text", word.get("word", "")),
            "sourceWordIndex": word.get("sourceWordIndex", index),
        }
        for index, word in enumerate(analysis.get("words", []))
    ]
    takes = [_search_take(chunk, segment) for chunk in _word_chunks(words)]
    groups = []
    current = []
    for take in takes:
        if current and not _related(current[-1], take):
            if len(current) > 1:
                groups.append(current)
            current = []
        current.append(take)
    if len(current) > 1:
        groups.append(current)
    return group_retakes(_grouped_utterances(groups))


def _grouped_utterances(groups):
    utterances = []
    for attempts in groups:
        identity = "retakes-" + content_hash([take["takeId"] for take in attempts])[:16]
        utterances.extend(
            {**take, "groupId": identity, "restart": True} for take in attempts
        )
    return utterances


def _bound_evidence(evidence: dict, analysis: dict, group: dict, source: dict) -> bool:
    checks = (
        analysis.get("sourceRef")
        == {"locator": source["locator"], "sha256": source["fingerprint"]["sha256"]},
        analysis.get("status") == "pass",
        bool(analysis.get("syncRef")),
        bool(analysis.get("routing")),
        evidence.get("sourceRef") == analysis.get("sourceRef"),
        evidence.get("syncRef") == analysis.get("syncRef"),
        evidence.get("routing") == analysis.get("routing"),
        evidence.get("groupHash") == content_hash(group),
        evidence.get("status") == "corroborated",
        bool(evidence.get("evidenceRefs")),
    )
    return all(checks)


def _contained(inner: dict, outer: dict) -> bool:
    source, start, end = source_interval(inner)
    other, first, last = source_interval(outer)
    return source == other and first <= start < end <= last


def _verified_group(group: dict, evidence: dict, segment: dict) -> dict | None:
    attempts = evidence.get("verifiedAttempts") or []
    originals = {take["takeId"]: take for take in group["attempts"]}
    if {take.get("takeId") for take in attempts} != set(originals):
        return None
    interval = _segment_range(segment)
    for take in attempts:
        if take.get("text") != originals[take["takeId"]]["text"] or not _contained(
            take["sourceRange"], interval
        ):
            return None
        if take["sourceRange"]["timebase"] != interval["timebase"]:
            return None
    return {**group, "attempts": attempts}


def _protections(ranges: list[dict], policy) -> list[str]:
    found = set()
    for protected in policy.protections if policy else ():
        source, start, end = source_interval(protected["sourceRange"])
        for interval in ranges:
            other, first, last = source_interval(interval)
            if source == other and max(start, first) < min(end, last):
                found.add(protected["eventId"])
    return sorted(found)


def _group_proposal(
    source, segment, analysis, analysis_ref, group, evidence_port, policy
):
    evidence = {}
    if evidence_port is not None:
        evidence = evidence_port.analyze_group(
            source,
            group,
            analysis,
            sync_ref=analysis.get("syncRef"),
            analysis_ref=analysis_ref,
        )
    verified = (
        _verified_group(group, evidence, segment)
        if _bound_evidence(evidence, analysis, group, source)
        else None
    )
    return _compose_selection(
        source, segment, group, verified, evidence, analysis_ref, policy
    )


def _compose_selection(
    source, segment, group, verified, evidence, analysis_ref, policy
):
    selection = (
        select_retake(verified, evidence)
        if verified
        else {
            "action": "needs-review",
            "reasons": [
                "Complete-take evidence is unavailable or not bound to current sources/Sync."
            ],
            "selectedTakeId": None,
            "rejectedTakeIds": [],
        }
    )
    attempts = (verified or group)["attempts"]
    rejected = [
        take for take in attempts if take["takeId"] in selection["rejectedTakeIds"]
    ]
    protections = _protections([take["sourceRange"] for take in rejected], policy)
    if protections:
        selection.update(
            action="keep",
            reasons=["A rejected candidate overlaps a hard protection."],
            selectedTakeId=None,
        )
    identity = occurrence_id(
        source["fingerprint"]["sha256"],
        source["sourceId"],
        {"retakeGroup": group["groupId"]},
    )
    occurrence = _selection_occurrence(
        identity, attempts, selection, protections, evidence, analysis_ref
    )
    edits = _selection_edits(identity, segment, rejected, selection["action"])
    return occurrence, edits


def _selection_occurrence(
    identity, attempts, selection, protections, evidence, analysis_ref
):
    occurrence = {
        "occurrenceId": identity,
        "sourceRange": _group_range(attempts),
        "categories": ["restart"],
        "disposition": selection["action"],
        "reasons": selection["reasons"],
        "protections": protections,
        "alternatives": deepcopy(attempts),
        "evidenceRefs": evidence.get("evidenceRefs")
        or ([analysis_ref] if analysis_ref else []),
    }
    if selection["selectedTakeId"]:
        occurrence["selectedAlternativeId"] = selection["selectedTakeId"]
    return occurrence


def _selection_edits(identity, segment, rejected, action):
    return (
        [
            {
                "occurrenceId": identity,
                "segmentId": segment["segmentId"],
                "removeRange": deepcopy(take["sourceRange"]),
            }
            for take in rejected
        ]
        if action == "replace"
        else []
    )


def _group_range(attempts: list[dict]) -> dict:
    interval = deepcopy(attempts[0]["sourceRange"])
    interval["startTicks"] = min(take["sourceRange"]["startTicks"] for take in attempts)
    interval["endTicksExclusive"] = max(
        take["sourceRange"]["endTicksExclusive"] for take in attempts
    )
    return interval


def propose_retakes(
    snapshot: dict,
    analyses: dict,
    *,
    analysis_refs=None,
    evidence_port=None,
    policy=None,
):
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    occurrences, edits = [], []
    refs = analysis_refs or {}
    for segment in snapshot["segments"]:
        analysis = analyses.get(segment["segmentId"])
        if analysis is None:
            continue
        for group in discover_retake_groups(analysis, segment):
            occurrence, changes = _group_proposal(
                sources[segment["sourceId"]],
                segment,
                analysis,
                refs.get(segment["segmentId"]),
                group,
                evidence_port,
                policy,
            )
            occurrences.append(occurrence)
            edits.extend(changes)
    return occurrences, edits
