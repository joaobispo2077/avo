"""Pure planning and immutable plan resolution for /avo.shorts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from avo import shorts_captions, shorts_contract, shorts_media, shorts_provider

TranscribeRunner = Callable[[Path, Path], Path]


class PlanningError(shorts_contract.ContractValidationError):
    """The requested batch cannot resolve into a truthful executable plan."""


class TranscriptRequiredError(PlanningError):
    """Resolution requires a word-timed source transcript."""


def _normalized_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip().casefold()


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any] | None) -> dict:
    result = deepcopy(dict(base))
    for key, value in (override or {}).items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _word_bounds(word: Mapping[str, Any]) -> tuple[float, float] | None:
    if word.get("type", "word") != "word":
        return None
    start = word.get("start")
    end = word.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if start < 0 or end < start:
        return None
    return float(start), float(end)


def transcript_words(transcript: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return ordered, valid word records from supported AVO transcripts."""
    words: list[dict[str, Any]] = []
    prior_start = -1.0
    for raw in transcript.get("words") or []:
        bounds = _word_bounds(raw)
        text = str(raw.get("text") or "").strip()
        if bounds is None or not text:
            continue
        start, end = bounds
        if start < prior_start:
            raise PlanningError("transcript words must be ordered by start time")
        words.append({**dict(raw), "text": text, "start": start, "end": end})
        prior_start = start
    if not words:
        raise TranscriptRequiredError("a usable word-timed transcript is required")
    return words


def words_for_range(
    words: list[Mapping[str, Any]], start: float, end: float
) -> list[dict[str, Any]]:
    """Select words intersecting a source interval without changing their clock."""
    return [
        dict(word)
        for word in words
        if float(word["end"]) > start and float(word["start"]) < end
    ]


def _validate_candidate_distinctness(candidates: list[Mapping[str, Any]]) -> None:
    seen: dict[tuple[Any, ...], str] = {}
    for candidate in candidates:
        ranges = candidate.get("sourceSegments") or [candidate["sourceRange"]]
        key = (
            _normalized_text(candidate["viewerPromise"]),
            tuple((float(item["startSec"]), float(item["endSec"])) for item in ranges),
        )
        previous = seen.get(key)
        if previous is not None:
            raise PlanningError(
                f"candidate {candidate['id']} duplicates candidate {previous}: "
                "same viewer promise and source range"
            )
        seen[key] = str(candidate["id"])


def _resolved_source_segments(
    candidate: Mapping[str, Any],
    *,
    source_id: str,
    source_fingerprint: str,
    speed: float,
    source_duration: float,
) -> list[dict[str, Any]]:
    declared = candidate.get("sourceSegments")
    if declared is None:
        source_range = candidate["sourceRange"]
        declared = [
            {
                "order": 1,
                "sourceId": source_id,
                "startSec": source_range["startSec"],
                "endSec": source_range["endSec"],
                "rationale": candidate.get("coreIdea") or "legacy source range",
                "evidenceReference": candidate.get("editorialApprovalReference")
                or "legacy-v1.0-normalization",
            }
        ]
    output_cursor = 0.0
    resolved: list[dict[str, Any]] = []
    prior: list[dict[str, Any]] = []
    for position, raw in enumerate(declared, 1):
        segment = deepcopy(dict(raw))
        start, end = _validate_source_segment(
            segment,
            position=position,
            source_id=source_id,
            source_duration=source_duration,
            prior=prior,
        )
        duration = (end - start) / speed
        resolved.append(
            {
                **segment,
                "segmentId": f"{candidate['id']}-s{position:03d}",
                "sourceFingerprint": source_fingerprint,
                "outputStartSec": round(output_cursor, 6),
                "outputEndSec": round(output_cursor + duration, 6),
            }
        )
        output_cursor += duration
        prior.append(segment)
    return resolved


def _validate_source_segment(
    segment: Mapping[str, Any],
    *,
    position: int,
    source_id: str,
    source_duration: float,
    prior: list[dict[str, Any]],
) -> tuple[float, float]:
    if segment.get("order") != position:
        raise PlanningError(
            "source segment order must equal array position; segments are never auto-sorted"
        )
    if segment.get("sourceId") != source_id:
        raise PlanningError(f"source segment {position} references unknown sourceId")
    start, end = float(segment["startSec"]), float(segment["endSec"])
    if end <= start:
        raise PlanningError("source segment duration must be positive")
    if math.isfinite(source_duration) and end > source_duration + 1e-6:
        raise PlanningError(
            f"source segment {position} ends beyond source duration {source_duration:.3f}s"
        )
    overlaps = any(
        start < float(item["endSec"]) and end > float(item["startSec"])
        for item in prior
    )
    if overlaps and not segment.get("overlapApprovalReference"):
        raise PlanningError(
            f"source segment {position} overlaps an earlier segment without overlap approval"
        )
    return start, end


def _resolve_layout(defaults: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict:
    layout = _deep_merge(defaults, candidate.get("layoutOverride"))
    mode = layout.get("mode")
    anchor = layout.get("captionAnchor", "auto")
    if anchor == "auto":
        layout["captionAnchor"] = "seam" if mode == "split" else "bottom"
    if mode == "full-frame" and layout.get("captionAnchor") == "seam":
        raise PlanningError(
            f"candidate {candidate['id']} cannot use seam captions in full-frame mode"
        )
    if mode == "split" and "splitRatio" not in layout:
        layout["splitRatio"] = 0.5
    layout.setdefault("cropMode", defaults.get("cropMode", "cover"))
    layout.setdefault("labels", [])
    return layout


def _speed_for(
    policy: Mapping[str, Any], candidate: Mapping[str, Any]
) -> tuple[float, bool]:
    speed = float(candidate.get("requestedSpeed", policy["default"]))
    minimum = float(policy["minimum"])
    maximum = float(policy["maximum"])
    if not minimum <= speed <= maximum:
        raise PlanningError(
            f"candidate {candidate['id']} speed {speed:g} is outside "
            f"the allowed range {minimum:g}-{maximum:g}"
        )
    if candidate.get("requestedSpeed") is not None and not policy.get(
        "perShortAllowed", True
    ):
        raise PlanningError(
            f"candidate {candidate['id']} requests a speed override but policy forbids it"
        )
    threshold = float(policy.get("intelligibilityReviewRequiredAbove", maximum))
    return speed, speed > threshold


def _item_fingerprint(
    candidate: Mapping[str, Any],
    *,
    speed: float,
    layout: Mapping[str, Any],
    source_fingerprint: str,
    provider_tokens_fingerprint: str | None,
    caption_policy: Mapping[str, Any] | None = None,
    corrections: list[Mapping[str, Any]] | None = None,
) -> str:
    return shorts_contract.content_hash(
        {
            "candidate": candidate,
            "speed": speed,
            "layout": layout,
            "sourceFingerprint": source_fingerprint,
            "providerTokensFingerprint": provider_tokens_fingerprint,
            "captionPolicy": caption_policy,
            "corrections": corrections or [],
        }
    )


def _allocation_candidates(
    items: list[Mapping[str, Any]],
    candidates: list[Mapping[str, Any]],
    count: int,
    rule: str,
) -> list[str]:
    if rule == "lowest-visual-interest":
        scores = {
            str(candidate["id"]): float(candidate.get("visualInterestScore", 50))
            for candidate in candidates
        }
        ordered = sorted(items, key=lambda item: scores.get(str(item["id"]), 50))
        return [str(item["id"]) for item in ordered[:count]]
    return [str(item["id"]) for item in items[:count]]


def _source_context(
    request: Mapping[str, Any],
    transcript: Mapping[str, Any],
    supplied_fingerprint: str | None,
) -> tuple[str, str, float]:
    source_fingerprint = (
        supplied_fingerprint
        or request.get("source", {}).get("expectedFingerprint")
        or transcript.get("source", {}).get("sha256")
        or shorts_contract.content_hash(transcript)
    )
    if not re.fullmatch(r"[a-f0-9]{64}", str(source_fingerprint)):
        raise PlanningError("source fingerprint must be a SHA-256 hex digest")
    expected = request.get("source", {}).get("expectedFingerprint")
    if expected and expected != source_fingerprint:
        raise PlanningError("source fingerprint changed after the request was approved")
    source_id = str(request.get("source", {}).get("sourceId") or "master")
    declared_duration = request.get("source", {}).get("durationSec")
    duration = float(declared_duration) if declared_duration is not None else math.inf
    return str(source_fingerprint), source_id, duration


def _caption_plan(
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    layout: dict[str, Any],
    speed: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Mapping[str, Any], list[Any]]:
    caption_policy = _deep_merge(
        request["defaults"]["captions"], candidate.get("captionOverride")
    )
    caption_anchor = caption_policy.get("anchor", "auto")
    if caption_anchor == "auto":
        caption_anchor = layout["captionAnchor"]
    layout["captionAnchor"] = caption_anchor
    shorts_captions.validate_anchor(
        caption_anchor,
        layout_mode=layout["mode"],
        protected_regions=layout.get("protectedRegions") or [],
    )
    corrections = [
        correction
        for correction in request.get("corrections") or []
        if not correction.get("scopeCandidateIds")
        or candidate["id"] in correction["scopeCandidateIds"]
    ]
    captions, audit = shorts_captions.plan_segmented_captions(
        words,
        segments,
        corrections,
        policy=caption_policy,
        candidate_id=str(candidate["id"]),
        speed=speed,
    )
    return captions, audit, caption_policy, corrections


def resolve_batch(
    request: Mapping[str, Any],
    transcript: Mapping[str, Any],
    *,
    request_path: Path | str,
    plan_revision: int = 1,
    source_fingerprint: str | None = None,
    provider_tokens_fingerprint: str | None = None,
    provider_tokens: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one validated request into an immutable exact-count plan."""
    shorts_contract.validate_document(request, "request")
    if provider_tokens is None:
        provider_tokens = shorts_provider.load_provider_design_tokens(
            str(request["provider"])
        )
    if provider_tokens_fingerprint is None:
        provider_tokens_fingerprint = shorts_provider.provider_tokens_fingerprint(
            provider_tokens
        )
    candidates = sorted(request["candidates"], key=lambda item: item["order"])
    _validate_candidate_distinctness(candidates)
    words = transcript_words(transcript)
    speed_policy = request["defaults"]["speed"]
    max_duration = float(request["output"]["maxDurationSec"])
    source_fingerprint, source_id, source_duration = _source_context(
        request, transcript, source_fingerprint
    )

    items: list[dict[str, Any]] = []
    required_reviews: list[str] = []
    for candidate in candidates:
        speed, review_speed = _speed_for(speed_policy, candidate)
        segments = _resolved_source_segments(
            candidate,
            source_id=source_id,
            source_fingerprint=str(source_fingerprint),
            speed=speed,
            source_duration=source_duration,
        )
        selected_words = [
            word
            for segment in segments
            for word in words_for_range(
                words, float(segment["startSec"]), float(segment["endSec"])
            )
        ]
        if not selected_words:
            raise PlanningError(
                f"candidate {candidate['id']} source segments have no transcript words"
            )
        evidence = _normalized_text(candidate["sourceEvidence"])
        selected_text = _normalized_text(
            " ".join(str(word["text"]) for word in selected_words)
        )
        if evidence not in selected_text:
            raise PlanningError(
                f"candidate {candidate['id']} sourceEvidence is not present "
                "in its transcript-backed source range"
            )

        edited_duration = sum(
            float(segment["outputEndSec"]) - float(segment["outputStartSec"])
            for segment in segments
        )
        if edited_duration > max_duration + 1e-9:
            raise PlanningError(
                f"candidate {candidate['id']} edited duration "
                f"{edited_duration:.3f}s exceeds maxDurationSec {max_duration:g}"
            )
        layout = _resolve_layout(request["defaults"]["layout"], candidate)
        captions, correction_audit, caption_policy, scoped_corrections = _caption_plan(
            request, candidate, words, segments, layout, speed
        )
        fingerprint = _item_fingerprint(
            candidate,
            speed=speed,
            layout=layout,
            source_fingerprint=str(source_fingerprint),
            provider_tokens_fingerprint=provider_tokens_fingerprint,
            caption_policy=caption_policy,
            corrections=scoped_corrections,
        )
        item = {
            "id": candidate["id"],
            "order": candidate["order"],
            "coreIdea": candidate["coreIdea"],
            "viewerPromise": candidate["viewerPromise"],
            "postingTitle": candidate["postingTitle"],
            "sourceEvidence": candidate["sourceEvidence"],
            "speed": speed,
            "editedDurationSec": round(edited_duration, 6),
            "layout": layout,
            "captions": captions,
            "captionCorrectionAudit": correction_audit,
            "inputFingerprint": fingerprint,
            "expectedOutputBasename": (f"{request['batchId']}-short-{candidate['id']}"),
            "rightsReviewReferences": list(candidate.get("rightsNotes") or []),
            "factualReviewReferences": [
                candidate["editorialApprovalReference"],
                *(candidate.get("factualNotes") or []),
            ],
            "qcProfile": "shorts-proof",
        }
        if request.get("version") == "1.1":
            item["sourceSegments"] = segments
        else:
            item["sourceRange"] = deepcopy(candidate["sourceRange"])
        items.append(item)
        if review_speed:
            required_reviews.append(
                f"candidate {candidate['id']}: speech intelligibility review "
                f"required at {speed:g}x"
            )

    allocations: list[dict[str, str]] = []
    by_id = {item["id"]: item for item in items}
    for insertion in request.get("insertions") or []:
        allocation = insertion["allocation"]
        mode = allocation["mode"]
        if mode == "explicit":
            selected = list(allocation.get("candidateIds") or [])
        else:
            if mode == "count":
                count = int(allocation.get("count", 0))
            else:
                raw = len(items) * float(allocation.get("percentage", 0)) / 100
                rounding = allocation.get("roundingRule", "nearest")
                count = (
                    math.floor(raw)
                    if rounding == "floor"
                    else math.ceil(raw)
                    if rounding == "ceil"
                    else math.floor(raw + 0.5)
                )
            rule = str(allocation.get("selectionRule") or "ordered")
            selected = _allocation_candidates(items, candidates, count, rule)
        unknown = set(selected) - set(by_id)
        if unknown:
            raise PlanningError(
                f"insertion {insertion['id']} selects unknown candidates: {', '.join(sorted(unknown))}"
            )
        for candidate_id in selected:
            item = by_id[candidate_id]
            item["inputFingerprint"] = shorts_contract.content_hash(
                {
                    "baseFingerprint": item["inputFingerprint"],
                    "insertionPolicy": insertion,
                }
            )
            item["insertion"] = {
                "id": insertion["id"],
                "videoStreamIndex": insertion["videoStream"],
                "audioStreamIndex": insertion.get("audioStream"),
                "targetDurationSec": item["editedDurationSec"],
                "supportVolume": insertion["supportVolume"],
                "sourceTimeMap": shorts_media.finite_repeat_map(
                    insertion["approvedWindows"], item["editedDurationSec"]
                ),
                "rightsReference": insertion["rightsBasis"],
            }
            allocations.append(
                {
                    "candidateId": candidate_id,
                    "insertionId": insertion["id"],
                    "reason": f"{mode} allocation",
                }
            )

    request_path = Path(request_path)
    plan: dict[str, Any] = {
        "version": str(request.get("version") or "1.0"),
        "batchId": request["batchId"],
        "planRevision": plan_revision,
        "requestPath": str(request_path),
        "requestHash": shorts_contract.content_hash(request),
        "sourceFingerprint": str(source_fingerprint),
        "requestedCount": request["requestedCount"],
        "resolvedCount": len(items),
        "output": deepcopy(request["output"]),
        "items": items,
        "insertionAllocation": allocations,
        "warnings": [],
        "requiredHumanReviews": required_reviews,
        "planApproval": {"status": "pending", "reference": None, "timestamp": None},
        "planHash": "0" * 64,
    }
    if request.get("version") == "1.1":
        source = request["source"]
        plan.update(
            {
                "planVersion": "1.1",
                "batchRoot": request["batchRoot"],
                "batchRootSource": request["batchRootSource"],
                "source": {
                    "sourceId": source_id,
                    "masterPath": source["masterPath"],
                    "transcriptPath": source.get("transcriptPath"),
                    "mediaFingerprint": str(source_fingerprint),
                    "transcriptFingerprint": shorts_contract.content_hash(transcript),
                },
            }
        )
    if provider_tokens_fingerprint:
        plan["providerTokensFingerprint"] = provider_tokens_fingerprint
    if provider_tokens:
        plan["providerTokens"] = dict(provider_tokens)
    elif request.get("provider"):
        plan.setdefault("warnings", []).append(
            f"provider {request['provider']} has no resolved design tokens; using HyperFrames defaults"
        )
    plan["planHash"] = shorts_contract.plan_hash(plan)
    shorts_contract.validate_document(plan, "plan")
    return plan


def _resolve_relative(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _revision_from_path(path: Path) -> int:
    match = re.search(r"-v(\d{3})(?=\.json$)", path.name)
    return int(match.group(1)) if match else 1


def _next_revision_path(path: Path, revision: int) -> Path:
    if re.search(r"-v\d{3}(?=\.json$)", path.name):
        name = re.sub(r"-v\d{3}(?=\.json$)", f"-v{revision:03d}", path.name)
    else:
        name = f"{path.stem}-v{revision:03d}{path.suffix}"
    return path.with_name(name)


def validate_request_file(path: Path | str) -> dict[str, Any]:
    """Validate request contracts and local source/transcript paths."""
    request_path = Path(path).resolve()
    request = shorts_contract.load_document(request_path, "request")
    master = _resolve_relative(request_path.parent, request["source"]["masterPath"])
    if not master.is_file():
        raise PlanningError(f"source master does not exist: {master}")
    expected = request["source"].get("expectedFingerprint")
    if expected and _sha256_file(master) != expected:
        raise PlanningError("source master fingerprint does not match request")
    transcript_value = request["source"].get("transcriptPath")
    if transcript_value:
        transcript_path = _resolve_relative(request_path.parent, transcript_value)
        if not transcript_path.is_file():
            raise TranscriptRequiredError(
                f"declared source transcript does not exist: {transcript_path}"
            )
    return request


def resolve_request_file(
    request_path: Path | str,
    output_path: Path | str,
    *,
    transcribe_runner: TranscribeRunner | None = None,
) -> Path:
    """Resolve and atomically write/reuse an immutable plan revision."""
    request_path = Path(request_path).resolve()
    request = shorts_contract.load_document(request_path, "request")
    master = _resolve_relative(request_path.parent, request["source"]["masterPath"])
    if not master.is_file():
        raise PlanningError(f"source master does not exist: {master}")
    source_fingerprint = _sha256_file(master)
    expected = request["source"].get("expectedFingerprint")
    if expected and source_fingerprint != expected:
        raise PlanningError("source master fingerprint does not match request")

    transcript_value = request["source"].get("transcriptPath")
    if transcript_value:
        transcript_path = _resolve_relative(request_path.parent, transcript_value)
    else:
        if transcribe_runner is None:
            from avo.transcribe import transcribe_one

            transcribe_runner = transcribe_one
        transcript_path = transcribe_runner(master, request_path.parent)
    if not transcript_path.is_file():
        raise TranscriptRequiredError(
            f"a usable transcript could not be created at {transcript_path}"
        )
    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptRequiredError(
            f"source transcript is unreadable: {transcript_path}: {exc}"
        ) from exc

    target = Path(output_path).resolve()
    revision = _revision_from_path(target)
    plan = resolve_batch(
        request,
        transcript,
        request_path=request_path,
        plan_revision=revision,
        source_fingerprint=source_fingerprint,
    )
    if target.exists():
        existing = shorts_contract.load_document(target, "plan")
        if existing["planHash"] == plan["planHash"]:
            return target
        revision = max(revision + 1, int(existing["planRevision"]) + 1)
        target = _next_revision_path(target, revision)
        while target.exists():
            revision += 1
            target = _next_revision_path(target, revision)
        plan = resolve_batch(
            request,
            transcript,
            request_path=request_path,
            plan_revision=revision,
            source_fingerprint=source_fingerprint,
        )
    shorts_contract.atomic_write_json(target, plan)
    return target


def target_render_profile(
    plan: Mapping[str, Any], *, preview: bool = False
) -> dict[str, Any]:
    output = plan["output"]
    if preview:
        return {"preview": True, "width": 640, "height": 360}
    return {
        "preview": False,
        "width": int(output["width"]),
        "height": int(output["height"]),
    }


def render_profile_matches(
    stored: Mapping[str, Any] | None, target: Mapping[str, Any]
) -> bool:
    if not stored:
        return False
    return (
        bool(stored.get("preview")) == bool(target.get("preview"))
        and int(stored.get("width", 0)) == int(target["width"])
        and int(stored.get("height", 0)) == int(target["height"])
    )


def dirty_items(
    plan: Mapping[str, Any],
    status: Mapping[str, Any] | None,
    *,
    preview: bool = False,
) -> dict[str, list[str]]:
    """Explain exactly which outputs need rebuilding for the current plan."""
    target = target_render_profile(plan, preview=preview)
    previous = {
        str(item["shortId"]): item for item in (status or {}).get("items") or []
    }
    dirty: dict[str, list[str]] = {}
    for item in plan["items"]:
        short_id = str(item["id"])
        old = previous.get(short_id)
        reasons: list[str] = []
        if old is None:
            reasons.append("new-short")
        elif old.get("inputFingerprint") != item["inputFingerprint"]:
            reasons.append("input-fingerprint-changed")
        elif not render_profile_matches(old.get("renderProfile"), target):
            reasons.append("render-profile-changed")
        elif old.get("dirty"):
            reasons.extend(old.get("dirtyReasons") or ["status-marked-dirty"])
        elif old.get("state") not in {"proof-ready", "proof-approved", "delivered"}:
            reasons.append(f"state-{old.get('state', 'unknown')}")
        if reasons:
            dirty[short_id] = reasons
    return dirty
