"""Compile canonical placed originals onto independent picture and PCM clocks."""

from copy import deepcopy
from fractions import Fraction
from math import lcm
from pathlib import Path

from .event_clock import sample_rate_boundary
from .import_layout import audio_sample_ranges, seconds, validate_layout
from .initial_cut import _native_sample_rate, _resample_operation, _source_selection


def _boundary(value, rate):
    value = Fraction(value)
    return sample_rate_boundary(
        value.numerator, source_rate=value.denominator, target_rate=rate
    )


def _frame(value, fps):
    frame = seconds(value) * fps
    if frame.denominator != 1:
        raise ValueError("Placed picture boundaries require integral output frames")
    return frame.numerator


def _media(source, workspace, stream):
    locator = Path(source.get("locator") or source["fingerprint"]["locator"])
    if not locator.is_absolute():
        locator = Path(workspace.raw_dir) / locator
    return {
        "locator": str(locator),
        "sha256": source["fingerprint"]["sha256"],
        "mediaClass": source.get("mediaClass", "source"),
        "ancestry": deepcopy(source.get("ancestry", [])),
        "streamIndex": stream,
    }


def _raw_range(item):
    first, last = item["in"], item["out"]
    if first["timebase"] == last["timebase"]:
        return {
            "startTicks": first["ticks"],
            "endTicks": last["ticks"],
            "timebase": deepcopy(first["timebase"]),
        }
    start, end = seconds(first), seconds(last)
    denominator = lcm(start.denominator, end.denominator)
    return {
        "startTicks": int(start * denominator),
        "endTicks": int(end * denominator),
        "timebase": {"num": 1, "den": denominator},
    }


def _picture(snapshot, sources, tracks, workspace, fps, total_frames):
    placements = []
    for item in snapshot["layout"]["placements"]:
        if item["mediaKind"] == "audio":
            continue
        track = tracks[item["trackId"]]
        placements.append(
            {
                "placementId": item["placementId"],
                "trackId": item["trackId"],
                "sourceId": item["sourceId"],
                "mediaKind": item["mediaKind"],
                "source": _media(
                    sources[item["sourceId"]],
                    workspace,
                    item["routing"]["videoStreamIndex"],
                ),
                "sourceRange": _raw_range(item),
                "outputRange": {
                    "startFrame": _frame(item["start"], fps),
                    "endFrameExclusive": _frame(item["end"], fps),
                },
                "zOrder": track["order"],
                "enabled": item["enabled"] and track["enabled"],
            }
        )
    return {
        "operations": [
            {
                "operationId": "source-layout-program",
                "kind": "source-layout",
                "inputs": sorted({item["sourceId"] for item in placements}),
                "outputRange": {"startFrame": 0, "endFrameExclusive": total_frames},
                "parameters": {"background": "black", "placements": placements},
            }
        ]
    }


def _audio_source(item, source, workspace, ordinal, probe):
    selection = item["routing"]["audioSelection"]
    _, selection, locator, mapping = _source_selection(
        {**source, "streamMetadata": {"audioSelection": selection}}, workspace
    )
    native_rate = _native_sample_rate(selection, locator, probe)
    source_range, output_range = audio_sample_ranges(item)
    node_id = f"audio-source-{ordinal:04d}"
    node = {
        "nodeId": node_id,
        "kind": "source",
        "sourceSampleRate": native_rate,
        "targetSampleRate": 48000,
        "sourceRange": source_range,
        "outputRange": output_range,
        "sourceLayout": selection["sourceLayout"],
        "targetLayout": "stereo",
        "channelMap": mapping,
        "latencyCompensationSamples": 0,
    }
    operations = [
        {
            "operationId": f"trim-audio-{ordinal:04d}",
            "kind": "trim",
            "range": output_range,
            "parameters": {
                "nodeId": node_id,
                "sourceId": item["sourceId"],
                "source": _media(source, workspace, selection["streamIndex"]),
                "fadeInSamples": 0,
                "fadeOutSamples": 0,
            },
        },
        *_resample_operation(ordinal, node_id, native_rate, 48000, output_range),
    ]
    if "gainDb" in item:
        operations.append(
            {
                "operationId": f"gain-audio-{ordinal:04d}",
                "kind": "gain",
                "range": output_range,
                "parameters": {"nodeId": node_id, "gainDb": item["gainDb"]},
            }
        )
    return node, operations


def _audio(snapshot, sources, tracks, workspace, total_samples, probe):
    extent = {"startSample": 0, "endSampleExclusive": total_samples}
    nodes = [
        {
            "nodeId": "silence-program",
            "kind": "silence",
            "sourceSampleRate": 48000,
            "targetSampleRate": 48000,
            "sourceRange": extent,
            "outputRange": extent,
            "sourceLayout": "stereo",
            "targetLayout": "stereo",
            "channelMap": [0, 1],
            "latencyCompensationSamples": 0,
        }
    ]
    operations = []
    for ordinal, item in enumerate(snapshot["layout"]["placements"], 1):
        track = tracks[item["trackId"]]
        if (
            item["mediaKind"] != "audio"
            or not item["enabled"]
            or not track["enabled"]
            or item.get("muted", False)
            or track["muted"]
        ):
            continue
        node, source_operations = _audio_source(
            item, sources[item["sourceId"]], workspace, ordinal, probe
        )
        nodes.append(node)
        operations.extend(source_operations)
    if len(nodes) > 1:
        operations.append(
            {
                "operationId": "mix-source-program",
                "kind": "mix",
                "range": extent,
                "parameters": {},
            }
        )
    operations.append(
        {
            "operationId": "encode-program",
            "kind": "encode",
            "range": extent,
            "parameters": {},
        }
    )
    return {
        "sampleRate": 48000,
        "nodes": nodes,
        "operations": operations,
        "singleFinalEncode": True,
    }


def _validation_windows(layout, fps, total_frames):
    boundaries = {0, total_frames}
    for item in [*layout["placements"], *layout["gaps"]]:
        for key in ("start", "end"):
            boundaries.add(min(total_frames, _boundary(seconds(item[key]) * fps, 1)))
    radius = max(1, round(2 * fps))
    return [
        {
            "startFrame": max(0, boundary - radius),
            "endFrameExclusive": min(total_frames, boundary + radius),
        }
        for boundary in sorted(boundaries)
    ]


def placed_cut_proof_request(
    workspace,
    snapshot,
    *,
    iteration_id,
    output,
    frame_rate,
    width,
    height,
    sample_rate,
    sample_rate_probe,
):
    validate_layout(snapshot)
    layout, canonical = snapshot["layout"], snapshot["importOutput"]
    fps = Fraction(frame_rate["num"], frame_rate["den"])
    clock = layout["programClock"]["frameRate"]
    if sample_rate != 48000 or canonical["audioSampleRate"] != 48000:
        raise ValueError("Placed source assembly currently requires 48000 Hz audio")
    if fps != Fraction(clock["num"], clock["den"]):
        raise ValueError("Placed proof frame rate must preserve the canonical clock")
    if (
        min(width, height) <= 0
        or width * canonical["height"] != height * canonical["width"]
    ):
        raise ValueError(
            "Placed proof dimensions must preserve the canonical canvas aspect ratio"
        )
    total_frames = _frame(layout["duration"], fps)
    total_samples = _boundary(seconds(layout["duration"]), sample_rate)
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    tracks = {track["trackId"]: track for track in layout["tracks"]}
    return {
        "checkpoint": "cut-proof",
        "iterationId": iteration_id,
        "sourceFingerprints": {
            key: source["fingerprint"]["sha256"] for key, source in sources.items()
        },
        "renderProfile": "cut-proof-360p",
        "output": {
            "path": str(output),
            "width": width,
            "height": height,
            "frameRate": deepcopy(frame_rate),
            "audioSampleRate": sample_rate,
            "channelLayout": "stereo",
            "videoCodec": "libx264",
            "audioCodec": "aac",
        },
        "videoGraph": _picture(snapshot, sources, tracks, workspace, fps, total_frames),
        "audioGraph": _audio(
            snapshot, sources, tracks, workspace, total_samples, sample_rate_probe
        ),
        "events": [],
        "visionReviewPlanRef": None,
        "validationPlan": {
            "preflight": [
                "canonical-lock",
                "original-source-fingerprints",
                "audio-routing",
            ],
            "microproof": _validation_windows(layout, fps, total_frames),
            "fullReview": ["transcript", "sequential-decode", "watch", "listening"],
            "historicalRegression": [],
        },
    }
