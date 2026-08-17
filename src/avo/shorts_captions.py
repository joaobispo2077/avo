"""Pure caption planning for parameter-driven Shorts compositions."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any


class CaptionError(ValueError):
    """Caption source, correction, timing, or layout policy is invalid."""


def normalize_pt_br(text: str) -> str:
    """Normalize common PT-BR currency and number transcription forms."""
    value = re.sub(r"R\s*\$\s*", "R$ ", text, flags=re.IGNORECASE)
    value = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", ".", value)
    return re.sub(r"\s+", " ", value).strip()


def _matches(words: list[dict[str, Any]], index: int, match: list[str]) -> bool:
    actual = [
        str(word["text"]).casefold() for word in words[index : index + len(match)]
    ]
    return actual == [token.casefold() for token in match]


def _replacement_words(
    originals: list[dict[str, Any]], replacement: list[str]
) -> list[dict[str, Any]]:
    if not replacement:
        return []
    start = float(originals[0]["start"])
    end = float(originals[-1]["end"])
    step = (end - start) / len(replacement)
    result = []
    for index, text in enumerate(replacement):
        result.append(
            {
                **deepcopy(originals[min(index, len(originals) - 1)]),
                "text": text,
                "start": start + index * step,
                "end": end
                if index == len(replacement) - 1
                else start + (index + 1) * step,
            }
        )
    return result


def apply_corrections(
    words: Iterable[Mapping[str, Any]],
    corrections: Iterable[Mapping[str, Any]],
    *,
    candidate_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply only reviewed corrections and return an explicit audit trail."""
    result = [deepcopy(dict(word)) for word in words]
    audit: list[dict[str, Any]] = []
    for correction_index, correction in enumerate(corrections):
        scopes = correction.get("scopeCandidateIds")
        if scopes and candidate_id not in scopes:
            continue
        if not correction.get("approved"):
            raise CaptionError(f"correction {correction_index} is not approved")
        match = [str(value) for value in correction.get("match") or []]
        if not match:
            raise CaptionError(f"correction {correction_index} has no match tokens")
        operation = str(correction["operation"])
        replacement = [str(value) for value in correction.get("replacement") or []]
        if operation == "omit" and not correction.get("reason"):
            raise CaptionError("omission requires a reviewed reason")
        if operation != "omit" and not replacement:
            raise CaptionError(f"{operation} correction requires replacement tokens")
        index = 0
        applied = False
        while index <= len(result) - len(match):
            if not _matches(result, index, match):
                index += 1
                continue
            originals = result[index : index + len(match)]
            new_words = (
                []
                if operation == "omit"
                else _replacement_words(originals, replacement)
            )
            result[index : index + len(match)] = new_words
            audit.append(
                {
                    "correctionIndex": correction_index,
                    "operation": operation,
                    "match": match,
                    "replacement": replacement,
                    "reason": correction["reason"],
                    "candidateId": candidate_id,
                }
            )
            index += max(1, len(new_words))
            applied = True
        if not applied:
            audit.append(
                {
                    "correctionIndex": correction_index,
                    "operation": operation,
                    "status": "not-matched",
                    "candidateId": candidate_id,
                }
            )
    return result, audit


def map_to_edited_time(
    words: Iterable[Mapping[str, Any]],
    *,
    source_start: float,
    source_end: float,
    speed: float,
    duration: float,
) -> list[dict[str, Any]]:
    if speed <= 0:
        raise CaptionError("speed must be positive")
    mapped = []
    for word in words:
        if float(word["end"]) <= source_start or float(word["start"]) >= source_end:
            continue
        start = max(source_start, float(word["start"]))
        end = min(source_end, float(word["end"]))
        mapped.append(
            {
                **deepcopy(dict(word)),
                "text": normalize_pt_br(str(word["text"])),
                "start": max(0.0, min(duration, (start - source_start) / speed)),
                "end": max(0.0, min(duration, (end - source_start) / speed)),
            }
        )
    return mapped


def _break_after(word: Mapping[str, Any]) -> bool:
    return bool(re.search(r"[.!?;:]$", str(word["text"])))


def group_words(
    words: list[dict[str, Any]], policy: Mapping[str, Any]
) -> list[list[dict[str, Any]]]:
    """Group words without loss using count, character, duration, gap, and punctuation."""
    if not words:
        return []
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        proposed = [*current, word]
        chars = len(" ".join(str(item["text"]) for item in proposed))
        duration = float(word["end"]) - float(proposed[0]["start"])
        gap = float(word["start"]) - float(current[-1]["end"]) if current else 0
        exceeds = current and (
            len(proposed) > int(policy["maxWords"])
            or chars > int(policy["maxCharacters"])
            or duration > float(policy["maxDurationSec"])
            or gap > float(policy["maxGapSec"])
        )
        if exceeds:
            groups.append(current)
            current = []
        current.append(word)
        if _break_after(word):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    if policy.get("mergeOrphans") and len(groups) > 1 and len(groups[-1]) == 1:
        merged = [*groups[-2], *groups[-1]]
        if len(merged) <= int(policy["maxWords"]):
            groups[-2:] = [merged]
        elif len(groups[-2]) > 1:
            orphan = groups[-1]
            orphan.insert(0, groups[-2].pop())
    return groups


def _rects_overlap(a: Mapping[str, float], b: Mapping[str, float]) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def validate_anchor(
    anchor: str,
    *,
    layout_mode: str,
    protected_regions: Iterable[Mapping[str, float]] = (),
    reviewed_override: bool = False,
) -> None:
    if anchor == "seam" and layout_mode != "split":
        raise CaptionError("seam anchor requires split layout")
    zones = {
        "top": {"x": 0.05, "y": 0.08, "width": 0.9, "height": 0.2},
        "center": {"x": 0.05, "y": 0.4, "width": 0.9, "height": 0.2},
        "bottom": {"x": 0.05, "y": 0.72, "width": 0.9, "height": 0.2},
        "seam": {"x": 0.05, "y": 0.42, "width": 0.9, "height": 0.16},
    }
    if anchor not in zones:
        raise CaptionError(f"unknown caption anchor: {anchor}")
    if not reviewed_override and any(
        _rects_overlap(zones[anchor], region) for region in protected_regions
    ):
        raise CaptionError(f"{anchor} caption rail overlaps a protected region")


def _apply_punch_selection(
    group: list[dict[str, Any]], policy: Mapping[str, Any]
) -> None:
    highlight = policy.get("highlight") or {}
    if highlight.get("punchSelection") != "last-content-word":
        return
    for index in range(len(group) - 1, -1, -1):
        text = str(group[index]["text"]).strip()
        if text and not re.fullmatch(r"[^\w]+", text, flags=re.UNICODE):
            group[index]["punch"] = True
            return


def build_phrases(
    words: list[dict[str, Any]],
    policy: Mapping[str, Any],
    *,
    duration: float,
) -> list[dict[str, Any]]:
    timing = policy["timing"]
    epsilon = float(timing["frameEpsilon"])
    minimum_hold = float(timing["minimumHoldSec"])
    tail = float(timing["tailPadSec"])
    groups = group_words(words, policy["grouping"])
    phrases: list[dict[str, Any]] = []
    for phrase_index, group in enumerate(groups):
        group = [dict(word) for word in group]
        _apply_punch_selection(group, policy)
        next_start = (
            float(groups[phrase_index + 1][0]["start"])
            if phrase_index + 1 < len(groups)
            else duration
        )
        natural_end = min(duration, float(group[-1]["end"]) + tail)
        end = min(
            natural_end,
            max(float(group[0]["start"]) + minimum_hold, next_start - epsilon),
        )
        autofixes: list[str] = []
        if end < natural_end - 1e-9:
            if timing["autofixPolicy"] == "fail":
                raise CaptionError("caption phrase overlap requires normalization")
            autofixes.append(f"clamped end from {natural_end:.6f} to {end:.6f}")
        phrase_start = float(group[0]["start"])
        caption_words = []
        for word_index, word in enumerate(group):
            word_start = max(phrase_start, float(word["start"]))
            word_end = min(end, float(word["end"]))
            following = (
                float(group[word_index + 1]["start"])
                if word_index + 1 < len(group)
                else end
            )
            highlight_exit = min(word_end, max(word_start, following - epsilon), end)
            caption_words.append(
                {
                    "id": f"p{phrase_index + 1}-w{word_index + 1}",
                    "text": html.escape(str(word["text"]), quote=True),
                    "startSec": round(word_start, 6),
                    "endSec": round(max(word_start, word_end), 6),
                    "punch": bool(word.get("punch", False)),
                    "highlightEnterSec": round(word_start, 6),
                    "highlightExitSec": round(highlight_exit, 6),
                }
            )
        phrases.append(
            {
                "id": f"phrase-{phrase_index + 1}",
                "startSec": round(phrase_start, 6),
                "endSec": round(end, 6),
                "renderedText": " ".join(str(word["text"]) for word in group),
                "words": caption_words,
                "autofixes": autofixes,
            }
        )
    return phrases


def active_word_at(phrases: Iterable[Mapping[str, Any]], at_sec: float) -> str | None:
    """Reference seek state: no highlight can leak across a phrase boundary."""
    for phrase in phrases:
        if not float(phrase["startSec"]) <= at_sec < float(phrase["endSec"]):
            continue
        for word in phrase["words"]:
            if (
                float(word["highlightEnterSec"])
                <= at_sec
                < float(word["highlightExitSec"])
            ):
                return str(word["id"])
        return None
    return None


def plan_captions(
    source_words: Iterable[Mapping[str, Any]],
    corrections: Iterable[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    candidate_id: str,
    source_start: float,
    source_end: float,
    speed: float,
    duration: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    corrected, audit = apply_corrections(
        source_words, corrections, candidate_id=candidate_id
    )
    mapped = map_to_edited_time(
        corrected,
        source_start=source_start,
        source_end=source_end,
        speed=speed,
        duration=duration,
    )
    return build_phrases(mapped, policy, duration=duration), audit
