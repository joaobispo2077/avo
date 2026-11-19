"""Retain native combined PCM facts for selected sound review windows."""

import math
import re

from .event_clock import frame_to_sample

SPEECH_BAND_HZ = (300, 4000)


def _sample_window(plan, window, rate):
    if window is None:
        return next(
            (
                operation["range"]
                for operation in plan["audioGraph"]["operations"]
                if operation["kind"] == "encode"
            ),
            None,
        )
    fps = plan["output"]["frameRate"]
    return {
        sample: frame_to_sample(
            window[frame],
            frame_rate_num=fps["num"],
            frame_rate_den=fps["den"],
            sample_rate=rate,
        )
        for sample, frame in (
            ("startSample", "startFrame"),
            ("endSampleExclusive", "endFrameExclusive"),
        )
    }


def _sound_event_ranges(plan):
    effects = {
        node["nodeId"]: node["outputRange"]
        for node in plan["audioGraph"]["nodes"]
        if node["kind"] == "sfx"
    }
    ranges = {}
    for event in plan.get("events", []):
        node = (event.get("audio") or {}).get("nodeId")
        if node in effects:
            ranges[event["eventId"]] = (node, effects[node])
    return ranges


def _events_in_window(ranges, window):
    first, last = window["startSample"], window["endSampleExclusive"]
    return sorted(
        identity
        for identity, (_, region) in ranges.items()
        if region["startSample"] < last and first < region["endSampleExclusive"]
    )


def _finite_db(value):
    return (
        value is None
        or type(value) is int
        or (type(value) is float and math.isfinite(value))
    )


def _is_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_levels(measurement, keys):
    if not isinstance(measurement, dict) or not all(
        key in measurement and _finite_db(measurement[key]) for key in keys
    ):
        return None
    return {key: measurement[key] for key in keys}


def _observed_native_mix(mix, expected, rate):
    if not isinstance(mix, dict):
        return None
    count = expected["endSampleExclusive"] - expected["startSample"]
    observed = (
        mix.get("sampleRate"),
        mix.get("sampleCount"),
        mix.get("window"),
        mix.get("pcmCodec"),
    )
    if observed != (rate, count, expected, "pcm_f32le"):
        return None
    channels = mix.get("channels")
    pcm_output = mix.get("output")
    pcm = pcm_output.get("sha256") if isinstance(pcm_output, dict) else None
    graph = mix.get("graphHash")
    if (
        type(channels) is not int
        or channels < 1
        or not _is_digest(pcm)
        or not _is_digest(graph)
    ):
        return None
    levels = _valid_levels(mix.get("measurement"), ("peakDbfs", "rmsDbfs"))
    if levels is None:
        return None
    return {
        "channels": channels,
        "mixGraphHash": graph,
        "pcmSha256": pcm,
        **levels,
    }


def _compare_dialogue_levels(levels, margin):
    dialogue, effect = levels["dialogueRmsDbfs"], levels["effectRmsDbfs"]
    if dialogue is None or effect is None:
        state = "sidechain-silent" if dialogue is None else "effect-silent"
        return {**levels, "status": state}
    actual = dialogue - effect
    deficit = max(0, margin - actual)
    return {
        **levels,
        "observedMarginDb": actual,
        "suggestedAdditionalAttenuationDb": deficit,
        "status": "below-selected-margin" if deficit else "meets-selected-margin",
    }


def _assess_balance(observed, margin):
    state = observed.get("status")
    if state == "bounded-review-required":
        return {"status": state}
    levels = _valid_levels(observed, ("dialogueRmsDbfs", "effectRmsDbfs"))
    if state != "measured" or levels is None:
        return {"status": "measurement-unavailable"}
    return _compare_dialogue_levels(levels, margin)


def _dialogue_receipt(event, region, window, margin, observed):
    overlap = {
        "startSample": max(region["startSample"], window["startSample"]),
        "endSampleExclusive": min(
            region["endSampleExclusive"], window["endSampleExclusive"]
        ),
    }
    if (
        observed.get("window"),
        observed.get("minimumDialogueMarginDb"),
        observed.get("bandHz"),
    ) != (overlap, margin, list(SPEECH_BAND_HZ)):
        observed = {}
    return {
        "eventId": event,
        "window": overlap,
        "minimumDialogueMarginDb": margin,
        "bandHz": list(SPEECH_BAND_HZ),
        **_assess_balance(observed, margin),
    }


def _balance_rows(rows):
    if not isinstance(rows, list):
        return {}
    return {
        row["nodeId"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("nodeId"), str)
    }


def _dialogue_balance(plan, ranges, event_ids, window, mix):
    selected = {
        operation["parameters"]["nodeId"]: operation["parameters"][
            "minimumDialogueMarginDb"
        ]
        for operation in plan["audioGraph"]["operations"]
        if operation["kind"] == "duck"
        and "minimumDialogueMarginDb" in operation["parameters"]
    }
    if not selected:
        return []
    observed = _balance_rows(mix.get("dialogueBalance"))
    result = []
    for event in event_ids:
        node, region = ranges[event]
        if node in selected:
            result.append(
                _dialogue_receipt(
                    event, region, window, selected[node], observed.get(node, {})
                )
            )
    return result


def summarize_sound_mix(plan, rendered, window):
    """Attach observed pre-encode sample levels without implying listening approval."""
    if not plan.get("events"):
        return None
    ranges = _sound_event_ranges(plan)
    if not ranges:
        return None
    rate = plan["output"]["audioSampleRate"]
    expected = _sample_window(plan, window, rate)
    if expected is None:
        return None
    event_ids = _events_in_window(ranges, expected)
    if not event_ids:
        return None
    identity = {
        "eventIds": event_ids,
        "window": expected,
        "sampleRate": rate,
        "proofPlanHash": plan["proofPlanHash"],
        "candidateSha256": rendered["output"]["sha256"],
    }
    mix = rendered.get("audioMix") or {}
    observed = _observed_native_mix(mix, expected, rate)
    if observed is None:
        return {
            **identity,
            "status": "unavailable",
            "reason": "native-mix-measurement-unavailable",
        }
    peak = observed["peakDbfs"]
    dialogue = _dialogue_balance(plan, ranges, event_ids, expected, mix)
    return {
        **identity,
        **observed,
        "status": "measured",
        "assessment": "pre-encode-pcm-sample-peak",
        "fullScaleHeadroomDb": None if peak is None else -peak,
        "aboveFullScale": peak is not None and peak > 0,
        **({"dialogueBalance": dialogue} if dialogue else {}),
    }
