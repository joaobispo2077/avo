"""Pure planning and immutable plan resolution for /avo.shorts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
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


def _motion_from_candidate(
    candidate: Mapping[str, Any], edited_duration: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    override = candidate.get("motionOverride") or {}
    callouts = deepcopy(list(override.get("callouts") or []))
    punch_ins = deepcopy(list(override.get("punchIns") or []))
    graphics = deepcopy(list(override.get("graphics") or []))
    short_id = candidate["id"]
    rows = (*callouts, *punch_ins, *graphics)
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise PlanningError(f"candidate {short_id} motion IDs must be unique")
    for row in rows:
        _validate_motion_window(short_id, row, edited_duration)
    for graphic in graphics:
        _validate_graphic_parameters(graphic)
    return callouts, punch_ins, graphics


def _validate_motion_window(
    short_id: str, row: Mapping[str, Any], edited_duration: float
) -> None:
    start, end = float(row["startSec"]), float(row["endSec"])
    if end <= start:
        raise PlanningError(
            f"candidate {short_id} motion {row.get('id')} must have positive duration"
        )
    if end > edited_duration + 1e-6:
        raise PlanningError(
            f"candidate {short_id} motion {row.get('id')} ends after edited duration"
        )
    if row.get("kind") == "stamp" and (end - start) < 1.0 - 1e-9:
        raise PlanningError(
            f"candidate {short_id} stamp {row.get('id')} must hold at least 1s"
        )


def _require_active_clock(
    graphic_id: str, start: float, end: float, label: str, value: Any
) -> None:
    clock = float(value)
    if clock < start or clock >= end:
        raise PlanningError(
            f"graphic {graphic_id} {label} must be within [{start:g}, {end:g})"
        )


def _validate_graphic_clocks(graphic: Mapping[str, Any]) -> None:
    start = float(graphic["startSec"])
    end = float(graphic["endSec"])
    params = graphic["params"]
    graphic_id = graphic["id"]
    for key in ("resolveAtSec", "wipeAtSec", "metacriticAtSec", "downbeatAtSec"):
        if params.get(key) is not None:
            _require_active_clock(graphic_id, start, end, key, params[key])
    for key in ("items", "roles", "badges"):
        for index, value in enumerate(params.get(key) or [], 1):
            if isinstance(value, Mapping):
                clock = value.get("startSec", value.get("atSec"))
                if clock is not None:
                    _require_active_clock(
                        graphic_id, start, end, f"{key}[{index}] time", clock
                    )
    for key in ("reject", "confirm", "badge"):
        value = params.get(key)
        if isinstance(value, Mapping):
            _require_active_clock(
                graphic_id, start, end, f"{key}.atSec", value["atSec"]
            )


def _star_fill_count(filled: float) -> int:
    if filled <= 0:
        return 0
    return math.ceil(filled - 1e-9)


def _validate_stars_widget(graphic: Mapping[str, Any]) -> None:
    start = float(graphic["startSec"])
    end = float(graphic["endSec"])
    params = graphic["params"]
    graphic_id = graphic["id"]
    total = int(params["total"])
    filled = float(params["filled"])
    if filled > total:
        raise PlanningError(f"graphic {graphic_id} filled cannot exceed total")
    stagger = float(params.get("fillStaggerSec") or 0.12)
    if start + _star_fill_count(filled) * stagger > end + 1e-9:
        raise PlanningError(
            f"graphic {graphic_id} star fill timing exceeds graphic duration"
        )


def _validate_duration_meter_widget(graphic: Mapping[str, Any]) -> None:
    start = float(graphic["startSec"])
    end = float(graphic["endSec"])
    params = graphic["params"]
    graphic_id = graphic["id"]
    fill_duration = int(params["ticks"]) * float(params.get("fillStaggerSec") or 0.18)
    if start + fill_duration > end + 1e-9:
        raise PlanningError(
            f"graphic {graphic_id} meter fill timing exceeds graphic duration"
        )
    hold = params.get("meterHoldSec")
    if hold is not None and start + float(hold) >= end:
        raise PlanningError(
            f"graphic {graphic_id} meterHoldSec must end before the graphic"
        )


def _validate_graphic_parameters(graphic: Mapping[str, Any]) -> None:
    _validate_graphic_clocks(graphic)
    widget = graphic["widget"]
    if widget == "stars":
        _validate_stars_widget(graphic)
    elif widget == "duration-meter":
        _validate_duration_meter_widget(graphic)


def _graphic_sfx_events(graphic: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = graphic.get("sfx")
    if not raw:
        return []
    if isinstance(raw, Mapping):
        return [dict(raw)]
    return [dict(row) for row in raw]


def _graphic_item_times(
    graphic: Mapping[str, Any], params: Mapping[str, Any]
) -> list[float]:
    items = params.get("items") or []
    start = float(graphic["startSec"])
    stagger = float(params.get("itemStaggerSec") or 0.4)
    times: list[float] = []
    for index, item in enumerate(items):
        if isinstance(item, Mapping) and item.get("startSec") is not None:
            times.append(float(item["startSec"]))
        else:
            times.append(start + index * stagger)
    return times


def _every_start(graphic: Mapping[str, Any], offset: float) -> list[float]:
    return [float(graphic["startSec"]) + offset]


def _every_fill(graphic: Mapping[str, Any], offset: float) -> list[float]:
    params = graphic.get("params") or {}
    if "filled" in params:
        count = _star_fill_count(float(params.get("filled") or 0))
    else:
        count = int(params.get("ticks") or 0)
    stagger = float(params.get("fillStaggerSec") or 0.12)
    start = float(graphic["startSec"])
    return [start + offset + index * stagger for index in range(count)]


def _every_item(graphic: Mapping[str, Any], offset: float) -> list[float]:
    return [
        clock + offset
        for clock in _graphic_item_times(graphic, graphic.get("params") or {})
    ]


def _every_resolve(graphic: Mapping[str, Any], offset: float) -> list[float]:
    params = graphic.get("params") or {}
    return [float(params.get("resolveAtSec") or graphic["endSec"]) + offset]


def _every_named_node(
    graphic: Mapping[str, Any], offset: float, key: str
) -> list[float]:
    params = graphic.get("params") or {}
    node = params.get(key) or {}
    start = float(graphic["startSec"])
    clock = float(node.get("atSec") or start) if isinstance(node, Mapping) else start
    return [clock + offset]


def _every_role(graphic: Mapping[str, Any], offset: float) -> list[float]:
    params = graphic.get("params") or {}
    roles = params.get("roles") or []
    stagger = float(params.get("roleStaggerSec") or 0.5)
    start = float(graphic["startSec"])
    times: list[float] = []
    for index, role in enumerate(roles):
        if isinstance(role, Mapping) and role.get("atSec") is not None:
            times.append(float(role["atSec"]) + offset)
        else:
            times.append(start + offset + index * stagger)
    return times


def _every_downbeat(graphic: Mapping[str, Any], offset: float) -> list[float]:
    params = graphic.get("params") or {}
    return [float(params.get("downbeatAtSec") or graphic["endSec"]) + offset]


def _every_wipe(graphic: Mapping[str, Any], offset: float) -> list[float]:
    params = graphic.get("params") or {}
    return [float(params.get("wipeAtSec") or graphic["startSec"]) + offset]


_GRAPHIC_EVERY = {
    "start": _every_start,
    "fill": _every_fill,
    "item": _every_item,
    "resolve": _every_resolve,
    "reject": lambda graphic, offset: _every_named_node(graphic, offset, "reject"),
    "confirm": lambda graphic, offset: _every_named_node(graphic, offset, "confirm"),
    "badge": lambda graphic, offset: _every_named_node(graphic, offset, "badge"),
    "role": _every_role,
    "downbeat": _every_downbeat,
    "wipe": _every_wipe,
}


def _graphic_event_times(
    graphic: Mapping[str, Any], event: Mapping[str, Any]
) -> list[float]:
    if event.get("atSec") is not None:
        return [float(event["atSec"])]
    every = str(event.get("every") or "start")
    handler = _GRAPHIC_EVERY.get(every)
    if handler is None:
        raise PlanningError(
            f"graphic {graphic.get('id')} has unknown sfx.every {every!r}"
        )
    return handler(graphic, float(event.get("offsetSec") or 0))


def _sfx_from_graphics(graphics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for graphic in graphics:
        events = _graphic_sfx_events(graphic)
        graphic_id = str(graphic["id"])
        for event_index, event in enumerate(events):
            kind = str(event["kind"])
            times = _graphic_event_times(graphic, event)
            for hit_index, clock in enumerate(times):
                start = float(graphic["startSec"])
                end = float(graphic["endSec"])
                if clock < start or clock >= end:
                    raise PlanningError(
                        f"graphic {graphic_id} SFX event must be within "
                        f"[{start:g}, {end:g})"
                    )
                suffix = []
                if len(events) > 1:
                    suffix.append(str(event_index + 1))
                if len(times) > 1:
                    suffix.append(str(hit_index + 1))
                tail = f"-{'-'.join(suffix)}" if suffix else ""
                hits.append(
                    {
                        "id": f"{graphic_id}-sfx-{kind}{tail}",
                        "kind": kind,
                        "startSec": round(clock, 6),
                    }
                )
    return hits


def _callout_sfx_hits(
    callouts: Sequence[Mapping[str, Any]], occupied: set[float]
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for callout in callouts:
        start = float(callout["startSec"])
        kind = str(callout["kind"])
        hits.append(
            {
                "id": f"{callout['id']}-sfx",
                "kind": kind,
                "startSec": round(start, 6),
            }
        )
        if kind in {"stamp", "price"}:
            occupied.add(round(start, 2))
    return hits


def _punch_sfx_hits(
    punch_ins: Sequence[Mapping[str, Any]], occupied: set[float]
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for punch in punch_ins:
        start = float(punch["startSec"])
        if round(start, 2) in occupied:
            continue
        hits.append(
            {
                "id": f"{punch['id']}-sfx",
                "kind": "punch",
                "startSec": round(start, 6),
            }
        )
    return hits


def _require_sfx_library(
    short_id: str, hits: Sequence[Mapping[str, Any]], library: Mapping[str, Any]
) -> None:
    missing = sorted({hit["kind"] for hit in hits if not library.get(hit["kind"])})
    if missing:
        raise PlanningError(
            f"candidate {short_id} needs SFX library keys: {', '.join(missing)}"
        )


def _sfx_from_motion(
    *,
    short_id: str,
    callouts: Sequence[Mapping[str, Any]],
    punch_ins: Sequence[Mapping[str, Any]],
    layout: Mapping[str, Any],
    sfx: Mapping[str, Any] | None,
    graphics: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Derive UI hits from chips/stamps/graphics; punch at the same clock is skipped."""
    if not sfx:
        return []
    hits: list[dict[str, Any]] = []
    occupied: set[float] = set()
    if str(layout.get("mode")) == "split":
        hits.append({"id": f"s{short_id}-sfx-seam", "kind": "seam", "startSec": 0.0})
    hits.extend(_callout_sfx_hits(callouts, occupied))
    graphic_hits = _sfx_from_graphics(graphics or [])
    hits.extend(graphic_hits)
    occupied.update(round(float(hit["startSec"]), 2) for hit in graphic_hits)
    hits.extend(_punch_sfx_hits(punch_ins, occupied))
    _require_sfx_library(short_id, hits, sfx.get("library") or {})
    return hits


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


def _bind_source_fields(
    item: dict[str, Any],
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    segments: list[dict[str, Any]],
) -> None:
    if shorts_contract.uses_canonical_root(request.get("version")):
        item["sourceSegments"] = segments
        return
    item["sourceRange"] = deepcopy(candidate["sourceRange"])


def _apply_canonical_plan_identity(
    plan: dict[str, Any],
    request: Mapping[str, Any],
    source_id: str,
    source_fingerprint: str,
    transcript: Mapping[str, Any],
) -> None:
    if not shorts_contract.uses_canonical_root(request.get("version")):
        return
    source = request["source"]
    plan.update(
        {
            "planVersion": str(request.get("version") or "1.1"),
            "batchRoot": request["batchRoot"],
            "batchRootSource": request["batchRootSource"],
            "source": {
                "sourceId": source_id,
                "masterPath": source["masterPath"],
                "transcriptPath": source.get("transcriptPath"),
                "mediaFingerprint": source_fingerprint,
                "transcriptFingerprint": shorts_contract.content_hash(transcript),
            },
        }
    )


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
        callouts, punch_ins, graphics = _motion_from_candidate(
            candidate, edited_duration
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
        if callouts:
            item["callouts"] = callouts
        if punch_ins:
            item["punchIns"] = punch_ins
        if graphics:
            item["graphics"] = graphics
        sfx_hits = _sfx_from_motion(
            short_id=candidate["id"],
            callouts=callouts,
            punch_ins=punch_ins,
            layout=layout,
            sfx=(request.get("defaults") or {}).get("sfx"),
            graphics=graphics,
        )
        if sfx_hits:
            item["sfxHits"] = sfx_hits
        _bind_source_fields(item, request, candidate, segments)
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
    _apply_canonical_plan_identity(
        plan, request, source_id, str(source_fingerprint), transcript
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
