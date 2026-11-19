"""Retain native combined PCM facts for selected sound review windows."""

import math
import re

from .event_clock import frame_to_sample


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
        region = effects.get((event.get("audio") or {}).get("nodeId"))
        if region is not None:
            ranges[event["eventId"]] = region
    return ranges


def _events_in_window(ranges, window):
    first, last = window["startSample"], window["endSampleExclusive"]
    return sorted(
        identity
        for identity, region in ranges.items()
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


def _observed_levels(mix):
    measurement = mix.get("measurement")
    keys = ("peakDbfs", "rmsDbfs")
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
    levels = _observed_levels(mix)
    if levels is None:
        return None
    return {
        "channels": channels,
        "mixGraphHash": graph,
        "pcmSha256": pcm,
        **levels,
    }


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
    observed = _observed_native_mix(rendered.get("audioMix") or {}, expected, rate)
    if observed is None:
        return {
            **identity,
            "status": "unavailable",
            "reason": "native-mix-measurement-unavailable",
        }
    peak = observed["peakDbfs"]
    return {
        **identity,
        **observed,
        "status": "measured",
        "assessment": "pre-encode-pcm-sample-peak",
        "fullScaleHeadroomDb": None if peak is None else -peak,
        "aboveFullScale": peak is not None and peak > 0,
    }
