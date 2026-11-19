"""Prepare cue-specific review from a full encoded proof and its observed frames."""

from bisect import bisect_left
from copy import deepcopy
from fractions import Fraction
from math import ceil

from .contracts import content_hash
from .import_layout import seconds
from .motion_metadata import LIFECYCLE

_CANONICAL = {"cmap", "bmap", "tracks", "animation", "sync-map"}
_ASSEMBLY_LOCK_FIELDS = {
    "cmap": "cmapRevisionHash",
    "bmap": "bmapRevisionHash",
    "tracks": "tracksRevisionHash",
    "sync-map": "syncRevisionHash",
}
_SOUND = {"ambience", "music", "sfx"}
_TEXT = {"caption", "card", "end-screen", "text"}
_MOTION_KINDS = {"animation", "card", "end-screen", "transition"}
_FRAME_CATEGORIES = {
    "accessibility",
    "caption",
    "continuity",
    "layout",
    "movement",
    "visual-quality",
}


def _matches_materialization(identity, record):
    output = record.get("output") or {}
    materialization_hash = record.get("materializationHash")
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"materializationHash", "path"}
    }
    return (
        record.get("kind") in {"proof-plan", "assembly"}
        and output.get("sha256") == identity["sha256"]
        and output.get("sizeBytes") == identity["byteSize"]
        and record.get("renderProfile") == identity["renderProfile"]
        and materialization_hash == identity["dependencies"].get("materialization")
        and materialization_hash == content_hash(payload)
    )


def _canonical_hashes(record):
    lock = record.get("canonicalInputLock") or {}
    if record["kind"] == "assembly":
        return {
            artifact: lock.get(field)
            for artifact, field in _ASSEMBLY_LOCK_FIELDS.items()
        }
    return {name: lock.get(name) for name in sorted(_CANONICAL)}


def _current_canonical_hashes(workspace, record):
    canonical = _canonical_hashes(record)
    if record["kind"] == "assembly" and not all(canonical.values()):
        return None
    active = workspace.active_dependency_snapshot()
    if any(active.get(name) != sha256 for name, sha256 in canonical.items()):
        return None
    return canonical


def _current_bmap(workspace, identity, record):
    if (
        workspace is None
        or not record
        or not _matches_materialization(identity, record)
    ):
        return None
    canonical = _current_canonical_hashes(workspace, record) or {}
    bmap_hash = canonical.get("bmap")
    if not bmap_hash:
        return None
    store = workspace.store("bmap")
    head = store.load_index()["headRevisionId"]
    if head is None:
        return None
    revision = store.revision(head)
    return revision if revision["contentHash"] == bmap_hash else None


def _frame_rate(rate):
    num, den = rate.get("num"), rate.get("den")
    if (type(num), type(den)) != (int, int) or min(num, den) <= 0:
        return None
    return Fraction(num, den)


def _sample_clock(coverage, materialization):
    if coverage.get("sampling") != "native-frames":
        return None, []
    rate = _frame_rate(coverage.get("frameRate") or {})
    declared_rate = materialization.get("renderContract", {}).get("frameRate")
    if rate is None or (declared_rate and rate != _frame_rate(declared_rate)):
        return None, []
    frames = sorted(
        {
            frame
            for frame in coverage.get("observedFrames") or []
            if type(frame) is int and frame >= 0
        }
    )
    return rate, frames


def _cited_frames(finding, observed_ids):
    program = finding.get("programRange") or {}
    start, end = program.get("startFrame"), program.get("endFrameExclusive")
    if (type(start), type(end)) != (int, int):
        return set()
    return {
        frame
        for ref in finding.get("evidenceRefs") or []
        if ref.get("kind") == "decoded-frame"
        and (frame := observed_ids.get(ref.get("artifactId"))) is not None
        and start <= frame < end
    }


def _frame_checks(kind):
    if kind in _SOUND:
        return []
    checks = ["focus-and-depth", "source-caption-safe-regions"]
    if kind in _TEXT or kind == "animation":
        checks.append("glyphs-grouping-alignment")
    if kind in _MOTION_KINDS or kind in {"caption", "insert", "text"}:
        checks.extend(["alpha-compositing", "first-and-last-states"])
    return checks


def _cue_frames(cue, rate, frames):
    if rate is None:
        return None, []
    first = ceil(seconds(cue["start"]) * rate)
    stop = ceil(seconds(cue["end"]) * rate)
    return (
        {"startFrame": first, "endFrameExclusive": stop},
        frames[bisect_left(frames, first) : bisect_left(frames, stop)],
    )


def _cue_lifecycle(cue):
    lifecycle = (cue.get("animation") or {}).get("lifecycle") or {}
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    if cue["kind"] not in _MOTION_KINDS and not lifecycle:
        return {}
    return {phase: deepcopy(lifecycle.get(phase)) for phase in LIFECYCLE}


def _cue_report(cue, rate, frames, findings):
    kind = cue["kind"]
    program_frames, frames_in_cue = _cue_frames(
        cue, rate, frames if kind not in _SOUND else []
    )
    observed = set(frames_in_cue)
    related = [
        {"findingId": finding_id, "observedFrames": sorted(shared)}
        for finding_id, cited in findings
        if (shared := observed & cited)
    ]
    return {
        "cueId": cue["cueId"],
        "kind": kind,
        "intent": cue["intent"],
        "targetLayerId": cue["targetLayerId"],
        "start": deepcopy(cue["start"]),
        "end": deepcopy(cue["end"]),
        "lifecycle": _cue_lifecycle(cue),
        "programFrames": program_frames,
        "observedFrames": frames_in_cue,
        "frameChecks": _frame_checks(kind),
        "frameFindings": related,
        "playbackChecks": ["continuity-and-lip-sync"]
        + (["entrance-hold-payoff-exit", "handoffs"] if kind in _MOTION_KINDS else [])
        + (["reading-time"] if kind in _TEXT else []),
        "listeningChecks": ["dialogue-intelligibility", "cue-audibility-and-mix"],
        "continuousPlayback": "required",
        "listening": "required",
    }


def candidate_craft_report(workspace, identity, materialization, coverage, findings):
    """Project review needs, without promoting observations to a craft decision."""
    revision = _current_bmap(workspace, identity, materialization)
    if revision is None or not revision["snapshot"].get("cues"):
        return None
    rate, frames = _sample_clock(coverage, materialization)
    observed_ids = {f"frame-{frame}": frame for frame in frames}
    cited_frames = [
        (finding["findingId"], _cited_frames(finding, observed_ids))
        for finding in findings
        if finding.get("findingId") and finding.get("category") in _FRAME_CATEGORIES
    ]
    return {
        "candidateSha256": identity["sha256"],
        "candidateIdentityHash": identity["identityHash"],
        "materializationHash": materialization["materializationHash"],
        "bmapRevisionHash": revision["contentHash"],
        "canonicalRevisionHashes": _canonical_hashes(materialization),
        "scope": "encoded-full-proof",
        "frameRate": {"num": rate.numerator, "den": rate.denominator} if rate else None,
        "cues": [
            _cue_report(cue, rate, frames, cited_frames)
            for cue in revision["snapshot"]["cues"]
        ],
    }


def attach_craft_report(evidence, workspace, identity, materialization, coverage):
    report = candidate_craft_report(
        workspace, identity, materialization, coverage, evidence["findings"]
    )
    if report is not None:
        evidence.setdefault("reviewContext", {})["craftChecks"] = report
    return evidence


def report_from_review(manifest):
    watch = next((item for item in manifest["evidence"] if item["kind"] == "watch"), {})
    report = (watch.get("reviewContext") or {}).get("craftChecks") or {}
    candidate = manifest["candidate"]
    if (
        report.get("candidateIdentityHash") == candidate["identityHash"]
        and report.get("candidateSha256") == candidate["sha256"]
    ):
        return report
    return None


def craft_review_markdown(manifest):
    report = report_from_review(manifest)
    if report is None:
        return []
    lines = [
        "",
        "## Craft review",
        "",
        (
            "Use the planned cue states and the encoded frame observations below "
            "to guide playback and listening. Individual frames cover only the "
            "pictures cited. Review the timed sequence for continuity, reading "
            "time and lip sync, and listen for audibility and masking."
        ),
        "",
    ]
    cues = sorted(report["cues"], key=lambda cue: not cue["frameFindings"])
    for cue in cues[:12]:
        frame_count = len(cue["observedFrames"])
        findings = ", ".join(item["findingId"] for item in cue["frameFindings"])
        detail = f" Referenced findings: {findings}." if findings else ""
        lines.append(
            f"- `{cue['cueId']}` ({cue['kind']}) has {frame_count} sampled frames "
            f"from {float(seconds(cue['start'])):.3f} to {float(seconds(cue['end'])):.3f}s."
            f"{detail}"
        )
    if len(cues) > 12:
        lines.append(f"- See all {len(cues)} cues in `review.json`.")
    return lines
