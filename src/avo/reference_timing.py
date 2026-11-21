"""Interpret validated visual measurements on their original sampled clock."""

from bisect import bisect_left
from fractions import Fraction
from itertools import accumulate, groupby, pairwise
from math import log, sqrt

from .timeline.camera import ease_curve

CURVES = ("linear", "quadratic-in", "quadratic-out", "quadratic-in-out")
AXES = ("translateX", "translateY", "scale")


def _motion_state(item):
    _, row = item
    if row["status"] != "measured":
        return row["status"]
    motion, residual = row["global"], row["residual"]
    change = max(
        abs(motion["translateX"]),
        abs(motion["translateY"]),
        abs(motion["scale"] - 1),
        abs(motion["rotationDegrees"]) / 90,
        residual["p90DisplayDiagonal"],
    )
    return (
        "low-motion"
        if change <= 0.005 and residual["movingPoints"] <= 2
        else "active-motion"
    )


def _timing_candidates(ticks, rows):
    result = []
    previous_hold = False
    evidence = {"active-motion": "motion-onset", "cut-candidate": "candidate-cut"}
    for state, run in groupby(
        zip(pairwise(ticks), rows, strict=True), key=_motion_state
    ):
        intervals = [scope for scope, _ in run]
        first, last = intervals[0]
        if previous_hold and state in evidence:
            result.append(
                {
                    "kind": "reveal",
                    "startTicks": first,
                    "endTicks": last,
                    "evidence": evidence[state],
                }
            )
        previous_hold = state == "low-motion" and len(intervals) >= 2
        if previous_hold:
            result.append(
                {
                    "kind": "hold",
                    "startTicks": first,
                    "endTicks": intervals[-1][1],
                    "evidence": "low-motion",
                }
            )
    return result


def _brightness_direction(item):
    row = item[1]
    before, after = (row["brightness"][key] for key in ("before", "after"))
    if row["status"] == "cut-candidate" or abs(after - before) < 0.01:
        return None
    return "brightening" if after > before else "darkening"


def _fade_candidates(ticks, rows):
    result = []
    for direction, run in groupby(
        zip(pairwise(ticks), rows, strict=True), _brightness_direction
    ):
        steps = [(scope, row["brightness"]) for scope, row in run]
        if direction is None or len(steps) < 3:
            continue
        before, after = steps[0][1]["before"], steps[-1][1]["after"]
        travel = abs(after - before)
        largest_step = max(abs(value["after"] - value["before"]) for _, value in steps)
        if travel >= 0.15 and largest_step <= travel / 2:
            result.append(
                {
                    "direction": direction,
                    "startTicks": steps[0][0][0],
                    "endTicks": steps[-1][0][1],
                    "before": before,
                    "after": after,
                }
            )
    return result


def _dominant_progress(rows):
    deltas = {
        axis: [
            log(row["global"][axis]) if axis == "scale" else row["global"][axis]
            for row in rows
        ]
        for axis in AXES
    }
    travel = {axis: sum(map(abs, values)) for axis, values in deltas.items()}
    dominant = max(AXES, key=travel.get)
    total = travel[dominant]
    if total < 0.02 or sum(travel.values()) - total > total * 0.25:
        return None
    increments = deltas[dominant]
    signed = sum(increments)
    if abs(signed) < total * 0.98:
        return None
    return dominant, [value / signed for value in accumulate(increments, initial=0)]


def _curve_fit(ticks, progress):
    span = ticks[-1] - ticks[0]
    phases = [Fraction(tick - ticks[0], span) for tick in ticks]
    errors = []
    for curve in CURVES:
        squares = (
            (value - float(ease_curve(curve, phase))) ** 2
            for phase, value in zip(phases, progress, strict=True)
        )
        errors.append((sqrt(sum(squares) / len(phases)), curve))
    return sorted(errors)[:2]


def _easing(ticks, rows):
    if len(rows) < 4 or any(
        row["status"] != "measured" or abs(row["global"]["rotationDegrees"]) > 0.5
        for row in rows
    ):
        return "uninterpreted"
    selected = _dominant_progress(rows)
    if selected is None:
        return "uninterpreted"
    axis, progress = selected
    (error, curve), (next_error, _) = _curve_fit(ticks, progress)
    if error > 0.08 or next_error - error < 0.01:
        return "uninterpreted"
    return {
        "status": "approximate",
        "curve": curve,
        "axis": axis,
        "startTicks": ticks[0],
        "endTicks": ticks[-1],
        "progressRmse": error,
    }


def _audio_relationships(candidates, scope, audio):
    base = scope["timebase"]
    samples_per_tick = Fraction(base["num"], base["den"]) * audio["sampleRate"]
    onsets = sorted(set(audio["onsetSamples"]))
    relations = []
    radius = audio["clockUncertaintySamples"] + audio["windowSamples"]
    for candidate in candidates:
        if candidate["kind"] != "reveal":
            continue
        start, end = (candidate[key] for key in ("startTicks", "endTicks"))
        left = bisect_left(onsets, start * samples_per_tick - radius)
        right = bisect_left(onsets, end * samples_per_tick + radius)
        if left < right:
            relations.append(
                {
                    "startTicks": start,
                    "endTicks": end,
                    "onsetSamples": onsets[left:right],
                }
            )
    return relations


def _audio_interpretation(result, candidates, scope, audio):
    available = result["availableEvidence"]
    available["audio-word-timing"] = "unavailable"
    available["prepared-words"] = "not-selected"
    if audio is None:
        return
    result["audioTiming"] = audio
    if audio["status"] == "observed":
        available["audio-word-timing"] = "audio-candidates"
        result.setdefault(
            "timingCandidates", [row for row in candidates if row["kind"] == "reveal"]
        )
        result["audioRevealRelationships"] = _audio_relationships(
            candidates, scope, audio
        )


def interpret_reference_timing(ticks, rows, aspects, scope, *, audio=None):
    result = {"easing": "uninterpreted", "availableEvidence": {}}
    candidates = []
    if aspects.intersection({"hold-reveal", "audio-word-timing"}):
        candidates = _timing_candidates(ticks, rows)
    if "hold-reveal" in aspects:
        if any(row["status"] == "measured" for row in rows):
            result["timingCandidates"] = candidates
            result["availableEvidence"]["hold-reveal"] = "measured-candidates"
        else:
            result["availableEvidence"]["hold-reveal"] = "unavailable"
    if "easing" in aspects:
        result["easing"] = _easing(ticks, rows)
    if "brightness" in aspects:
        fades = _fade_candidates(ticks, rows)
        if fades:
            result["fadeCandidates"] = fades
    if "audio-word-timing" in aspects:
        _audio_interpretation(result, candidates, scope, audio)
    return result
