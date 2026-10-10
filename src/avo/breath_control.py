"""Opt-in, sample-domain breath gain and raw-only editorial cut proposals.

Detection proposes events, not diagnoses. Speech and source-sound protection
take precedence over coverage. No operation on a mixed master is permitted.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import pairwise
from math import isfinite
from typing import Any

import numpy as np


class BreathControlError(ValueError):
    """Unsafe or ambiguous breath processing request."""


DEFAULTS = {
    "action": "attenuate",
    "selection": "all",
    "sampleRate": 48000,
    "targetBelowSpeechDb": 20,
    "maxReductionDb": 9,
    "fixedReductionDb": 6,
    "longMs": 600,
    "heavyBelowSpeechDb": 15,
    "guardMs": 80,
    "fadeInMs": 30,
    "fadeOutMs": 50,
    "keepPauseMs": 250,
    "events": [],
    "protectedRanges": [],
}
ACTIONS = {"preserve", "attenuate", "fixed", "room-tone", "shorten", "cut", "hybrid"}
SELECTIONS = {"all", "long", "heavy", "long-or-heavy", "long-and-heavy", "manual"}


def resolve_control(control: dict | None, *, role: str = "dialogue") -> dict | None:
    """Missing/disabled settings are an identity operation, never an opt-in."""
    if control is None:
        return None
    if not isinstance(control, dict) or not isinstance(control.get("enabled"), bool):
        raise BreathControlError("breathControl requires explicit boolean enabled")
    if not control["enabled"]:
        return None
    if role != "dialogue":
        raise BreathControlError("breathControl is restricted to a dialogue layer")
    result = {**deepcopy(DEFAULTS), **deepcopy(control)}
    _validate_policy(result)
    _validate_numbers(result)
    return result


def _validate_numbers(result: dict) -> None:
    for field in DEFAULTS.keys() - {"action", "selection", "events", "protectedRanges"}:
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise BreathControlError(f"{field} must be numeric")
        if not isfinite(value) or value < 0:
            raise BreathControlError(f"{field} must be finite and non-negative")


def _validate_policy(result: dict) -> None:
    if result["action"] not in ACTIONS or result["selection"] not in SELECTIONS:
        raise BreathControlError("unsupported breath action or selection")
    if not isinstance(result["sampleRate"], int) or result["sampleRate"] <= 0:
        raise BreathControlError("sample rate must be a positive integer")
    if result["maxReductionDb"] > 60 or result["fixedReductionDb"] > 60:
        raise BreathControlError("breath gain exceeds the 60 dB safety bound")
    for field in ("events", "protectedRanges"):
        if not isinstance(result[field], list):
            raise BreathControlError(f"{field} must be an array")


def _range(event: dict, length: int | None = None) -> tuple[int, int]:
    start, end = event.get("startSample"), event.get("endSampleExclusive")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (start, end)):
        raise BreathControlError("breath range requires integer sample boundaries")
    if start < 0 or end <= start or (length is not None and end > length):
        raise BreathControlError("breath range is empty or outside the input")
    return start, end


def _level(event: dict, key: str) -> float:
    value = event.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise BreathControlError(f"breath event requires finite {key}")
    return float(value)


def _matches(event: dict, policy: dict, rate: int) -> bool:
    start, end = _range(event)
    long = (end - start) * 1000 / rate >= policy["longMs"]
    heavy = (
        _level(event, "breathRmsDb")
        >= _level(event, "speechRmsDb") - policy["heavyBelowSpeechDb"]
    )
    return {
        "all": True,
        "long": long,
        "heavy": heavy,
        "long-or-heavy": long or heavy,
        "long-and-heavy": long and heavy,
        "manual": event.get("manual") is True,
    }[policy["selection"]]


def select_events(
    control: dict, sample_rate: int, *, length: int | None = None
) -> list[dict]:
    policy = resolve_control(control)
    if policy is None or policy["action"] == "preserve":
        return []
    if "sampleRate" in control and policy["sampleRate"] != sample_rate:
        raise BreathControlError("breath sample rate does not match the dialogue")
    protection = [_range(item, length) for item in policy["protectedRanges"]]
    selected = [
        event
        for event in _reviewed_events(policy, length)
        if _safe_event(event, protection) and _matches(event, policy, sample_rate)
    ]
    selected.sort(key=lambda item: item["startSample"])
    _validate_overlap(selected)
    return selected


def _validate_overlap(selected: list[dict]) -> None:
    if any(a["endSampleExclusive"] > b["startSample"] for a, b in pairwise(selected)):
        raise BreathControlError("selected breath events overlap")


def _reviewed_events(policy: dict, length: int | None):
    identities = set()
    for event in policy["events"]:
        if not isinstance(event, dict) or not event.get("eventId"):
            raise BreathControlError("breath event requires an eventId")
        if event["eventId"] in identities:
            raise BreathControlError("duplicate breath event identity")
        identities.add(event["eventId"])
        _range(event, length)
        yield event


def _safe_event(event: dict, protection: list[tuple[int, int]]) -> bool:
    start, end = _range(event)
    return (
        event.get("status") in {"safe", "confirmed"}
        and not event.get("protected")
        and not any(start < right and end > left for left, right in protection)
    )


def _gain_db(event: dict, policy: dict) -> float:
    if policy["action"] == "room-tone":
        return float("-inf")
    if policy["action"] == "fixed":
        return -min(policy["fixedReductionDb"], policy["maxReductionDb"])
    target = _level(event, "speechRmsDb") - policy["targetBelowSpeechDb"]
    return max(-policy["maxReductionDb"], min(0, target - _level(event, "breathRmsDb")))


def gain_envelope(control: dict | None, length: int, sample_rate: int) -> np.ndarray:
    policy = resolve_control(control)
    envelope = np.ones(length, dtype=np.float32)
    if policy is None:
        return envelope
    if policy["action"] in {"shorten", "cut", "hybrid"}:
        raise BreathControlError("time deletion requires an approved raw-source CMap")
    for event in select_events(control, sample_rate, length=length):
        start, end = _range(event, length)
        gain = 10 ** (_gain_db(event, policy) / 20)
        span = end - start
        attack = min(round(policy["fadeInMs"] * sample_rate / 1000), span // 2)
        release = min(round(policy["fadeOutMs"] * sample_rate / 1000), span // 2)
        # Endpoints are unity: joins cannot introduce an amplitude step.
        values = np.full(span, gain, dtype=np.float32)
        if attack:
            values[:attack] = (
                gain + (1 - gain) * (1 + np.cos(np.linspace(0, np.pi, attack))) / 2
            )
        if release:
            values[-release:] = (
                gain + (1 - gain) * (1 - np.cos(np.linspace(0, np.pi, release))) / 2
            )
        envelope[start:end] = values
    return envelope


def apply_control(
    pcm: np.ndarray,
    control: dict | None,
    sample_rate: int,
    *,
    room_tone: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return processed dialogue and delta, preserving shape and untouched PCM."""
    policy = resolve_control(control)
    if not np.isfinite(pcm).all() or pcm.ndim not in {1, 2}:
        raise BreathControlError("dialogue PCM must be finite, mono or multichannel")
    envelope = gain_envelope(control, len(pcm), sample_rate)
    if pcm.ndim == 2:
        envelope = envelope[:, None]
    output = pcm * envelope
    if policy and policy["action"] == "room-tone":
        if (
            room_tone is None
            or room_tone.shape != pcm.shape
            or not np.isfinite(room_tone).all()
        ):
            raise BreathControlError(
                "room tone must be approved PCM matching the input"
            )
        output += room_tone * (1 - envelope)
    return output, pcm - output


def cut_proposals(control: dict, sample_rate: int) -> list[dict[str, Any]]:
    """Propose raw-source deletions; never splice audio independently of picture."""
    policy = resolve_control(control)
    if policy is None or policy["action"] not in {"shorten", "cut", "hybrid"}:
        return []
    proposals = []
    for event in select_events(control, sample_rate):
        if policy["action"] == "hybrid" and (
            (event["endSampleExclusive"] - event["startSample"]) * 1000 / sample_rate
            < policy["longMs"]
        ):
            continue
        raw = _raw_anchor(event)
        start, end = _range(raw)
        expected = (
            (event["endSampleExclusive"] - event["startSample"])
            * raw["sampleRate"]
            / sample_rate
        )
        if abs(end - start - expected) > 1:
            raise BreathControlError(
                "raw-source anchor duration does not match the event"
            )
        keep = (
            0
            if policy["action"] == "cut"
            else round(policy["keepPauseMs"] * raw["sampleRate"] / 1000)
        )
        if end - start <= keep:
            continue
        left = keep // 2
        proposals.append(
            {
                "eventId": event["eventId"],
                "sourceId": raw["sourceId"],
                "startSample": start + left,
                "endSampleExclusive": end - (keep - left),
                "sampleRate": raw["sampleRate"],
                "requiresCMapApproval": True,
            }
        )
    return proposals


def _raw_anchor(event: dict) -> dict:
    raw = event.get("rawAnchor") or {}
    rate = raw.get("sampleRate")
    if (
        not raw.get("sourceId")
        or isinstance(rate, bool)
        or not isinstance(rate, int)
        or rate <= 0
    ):
        raise BreathControlError("cut requires an exact raw-source anchor")
    return raw


def gain_filter(control: dict, *, role: str) -> str:
    """Compile the same smooth envelope at sample resolution for FFmpeg."""
    policy = resolve_control(control, role=role)
    if policy is None:
        return ""
    if policy["action"] not in {"preserve", "attenuate", "fixed"}:
        raise BreathControlError(
            "room-tone needs a materialized source; time deletion requires CMap"
        )
    terms = []
    for event in select_events(control, 48000):
        start, end = _range(event)
        gain = 10 ** (_gain_db(event, policy) / 20)
        span = end - start
        attack = min(round(policy["fadeInMs"] * 48), span // 2)
        release = min(round(policy["fadeOutMs"] * 48), span // 2)
        if attack < 2 or release < 2:
            raise BreathControlError(
                "breath event needs at least two fade samples per edge"
            )
        weight = f"if(lt(n,{start + attack}),(1-cos(PI*(n-{start})/{attack - 1}))/2,if(gte(n,{end - release}),(1+cos(PI*(n-{end - release})/{release - 1}))/2,1))"
        terms.append(f"if(between(n,{start},{end - 1}),({gain - 1:.12g})*({weight}),0)")
    if not terms:
        return ""
    expression = "1+" + "+".join(terms)
    return f"aeval=exprs='val(0)*({expression})|val(1)*({expression})':c=stereo,aformat=sample_fmts=flt"
