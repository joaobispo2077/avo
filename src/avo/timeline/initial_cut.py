"""Build the first source-only proof request from the current canonical CMap."""

import json
import subprocess
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

from avo.audio_restoration import validate_dialogue_noise_policy


def _dialogue_noise_parameters(metadata, selection, channel_map):
    if "dialogueNoiseReductionPolicy" not in metadata:
        return {}
    policy = validate_dialogue_noise_policy(
        metadata["dialogueNoiseReductionPolicy"], selection["streamIndex"], channel_map
    )
    return {"dialogueNoiseReductionPolicy": policy}


def _source_selection(source, workspace):
    metadata = source.get("streamMetadata") or {}
    selection = metadata.get("audioSelection") or {}
    if not selection or "streamIndex" not in selection:
        raise ValueError(f"canonical audio selection is required: {source['sourceId']}")
    if selection.get("outputLayout") not in {"dual-mono", "stereo"}:
        raise ValueError("initial proofs support explicit stereo or dual-mono routing")
    channels = list(selection["channels"])
    if not channels:
        raise ValueError("initial proofs require selected source channels")
    locator = Path(source.get("locator") or source["fingerprint"]["locator"])
    if not locator.is_absolute():
        locator = Path(workspace.raw_dir) / locator
    channel_map = (
        [channels[0], channels[0]]
        if selection["outputLayout"] == "dual-mono"
        else channels
    )
    return metadata, selection, locator, channel_map


def _native_sample_rate(selection, locator):
    declared = selection.get("sourceSampleRate")
    if declared is not None:
        return int(declared)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(locator)],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    stream = next(item for item in streams if item["index"] == selection["streamIndex"])
    if stream["codec_type"] != "audio":
        raise ValueError("canonical selected stream must contain audio")
    return int(stream["sample_rate"])


def _cached_native_rate(selection, locator, source_id, cache):
    if source_id not in cache:
        cache[source_id] = _native_sample_rate(selection, locator)
    return cache[source_id]


def _resample_operation(ordinal, node_id, native_rate, sample_rate, sample_range):
    if native_rate == sample_rate:
        return []
    return [
        {
            "operationId": f"resample-audio-{ordinal:04d}",
            "kind": "resample",
            "range": sample_range,
            "parameters": {
                "nodeId": node_id,
                "sourceSampleRate": native_rate,
                "targetSampleRate": sample_rate,
            },
        }
    ]


def _source_interval(segment):
    start, end = segment["in"], segment["out"]
    if start["timebase"] != end["timebase"]:
        raise ValueError("a source interval must use one timebase")
    timebase = Fraction(start["timebase"]["num"], start["timebase"]["den"])
    start_time, end_time = start["ticks"] * timebase, end["ticks"] * timebase
    if end_time <= start_time:
        raise ValueError(f"source interval must be positive: {segment['segmentId']}")
    return start, end, start_time, end_time


def _video_tail_parameters(metadata):
    if "videoTailPolicy" not in metadata:
        return {}
    policy = metadata["videoTailPolicy"]
    if not isinstance(policy, dict) or set(policy) != {"mode", "maxHoldMilliseconds"}:
        raise ValueError("canonical video tail policy requires exact mode/budget keys")
    budget = policy["maxHoldMilliseconds"]
    if (
        policy["mode"] != "hold-last-frame"
        or type(budget) is not int
        or not 1 <= budget <= 200
    ):
        raise ValueError(
            "canonical video tail policy must hold-last-frame for 1..200 ms"
        )
    return {"videoTailPolicy": deepcopy(policy)}


def _clock_boundary(value, precise):
    if not precise:
        return round(value)
    from .event_clock import sample_rate_boundary

    value = Fraction(value)
    return sample_rate_boundary(
        value.numerator, source_rate=value.denominator, target_rate=1
    )


def _precise_clock_mode(workspace, snapshot):
    return bool(
        snapshot.get("cuttingRef") or getattr(workspace, "cutting_preview", False)
    )


def _protected_windows(
    snapshot, locator, start_time, end_time, first, last, fps, precise=False
):
    windows = []
    for protected in snapshot.get("protectedQuizWindows", []):
        if Path(protected["sourceBasename"]).name != locator.name:
            continue
        hold_start = Fraction(str(protected["start"]))
        hold_end = Fraction(str(protected["end"]))
        if end_time <= hold_start or start_time >= hold_end:
            continue
        if not start_time <= hold_start < hold_end <= end_time:
            raise ValueError("a protected answer window was cut")
        minimum = Fraction(str(protected["minimumAnswerSeconds"]))
        window = {
            "startFrame": first
            + _clock_boundary((hold_start - start_time) * fps, precise),
            "endFrameExclusive": min(
                last, first + _clock_boundary((hold_end - start_time) * fps, precise)
            ),
        }
        if (
            hold_end - hold_start < minimum
            or window["endFrameExclusive"] - window["startFrame"] < minimum * fps
        ):
            raise ValueError(
                "a protected answer window is too short after frame conversion"
            )
        windows.append(window)
    return windows


def initial_cut_proof_request(
    workspace: Any,
    *,
    iteration_id: str,
    output: Path,
    frame_rate: dict[str, int],
    width: int = 640,
    height: int = 360,
    sample_rate: int = 48000,
) -> dict[str, Any]:
    """Preserve source routing and declare every join as a review obligation."""
    index = workspace.require_active("cmap")
    revision = workspace.store("cmap").revision(index["headRevisionId"])
    snapshot = revision["snapshot"]
    precise = _precise_clock_mode(workspace, snapshot)
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    fps = Fraction(frame_rate["num"], frame_rate["den"])
    if fps <= 0 or min(width, height, sample_rate) <= 0:
        raise ValueError(
            "proof dimensions, frame rate and sample rate must be positive"
        )
    operations, nodes, audio_ops = [], [], []
    elapsed = Fraction(0)
    joins = []
    protected_windows = []
    fingerprints = {}
    native_rates = {}
    for ordinal, segment in enumerate(snapshot["segments"], 1):
        source_id = segment["sourceId"]
        source = sources[source_id]
        metadata, selection, locator, channel_map = _source_selection(source, workspace)
        native_rate = _cached_native_rate(selection, locator, source_id, native_rates)
        start, end, start_time, end_time = _source_interval(segment)
        first = _clock_boundary(elapsed * fps, precise)
        elapsed += end_time - start_time
        last = _clock_boundary(elapsed * fps, precise)
        if last <= first:
            raise ValueError("source interval is shorter than one output frame")
        frame_range = {"startFrame": first, "endFrameExclusive": last}
        sample_range = {
            "startSample": _clock_boundary(
                Fraction(first, 1) / fps * sample_rate, precise
            ),
            "endSampleExclusive": _clock_boundary(
                Fraction(last, 1) / fps * sample_rate, precise
            ),
        }
        fingerprint = source["fingerprint"]["sha256"]
        fingerprints[source_id] = fingerprint
        media = {
            "locator": str(locator),
            "sha256": fingerprint,
            "mediaClass": source.get("mediaClass", "source"),
            "ancestry": source.get("ancestry", []),
        }
        node_id = f"audio-source-{ordinal:04d}"
        nodes.append(
            {
                "nodeId": node_id,
                "kind": "source",
                "sourceSampleRate": native_rate,
                "targetSampleRate": sample_rate,
                "sourceRange": {
                    "startSample": _clock_boundary(start_time * native_rate, precise),
                    "endSampleExclusive": _clock_boundary(
                        end_time * native_rate, precise
                    ),
                },
                "outputRange": sample_range,
                "sourceLayout": selection["sourceLayout"],
                "targetLayout": "stereo",
                "channelMap": channel_map,
                "latencyCompensationSamples": 0,
            }
        )
        operations.append(
            {
                "operationId": f"trim-source-{ordinal:04d}",
                "kind": "trim",
                "inputs": [source_id],
                "outputRange": frame_range,
                "parameters": {
                    **_video_tail_parameters(metadata),
                    "sourceId": source_id,
                    "source": {**media, "streamIndex": metadata["videoStreamIndex"]},
                    "sourceRange": {
                        "startTicks": start["ticks"],
                        "endTicks": end["ticks"],
                        "timebase": start["timebase"],
                    },
                },
            }
        )
        # Keep the 30 ms envelope where it fits. Short valid fragments need
        # bounded, non-overlapping ramps rather than impossible 30 ms fades.
        fade_samples = min(
            round(sample_rate * Fraction(3, 100)),
            (sample_range["endSampleExclusive"] - sample_range["startSample"]) // 2,
        )
        audio_ops.append(
            {
                "operationId": f"trim-audio-{ordinal:04d}",
                "kind": "trim",
                "range": sample_range,
                "parameters": {
                    **_dialogue_noise_parameters(metadata, selection, channel_map),
                    "nodeId": node_id,
                    "sourceId": source_id,
                    "source": {**media, "streamIndex": selection["streamIndex"]},
                    "fadeInSamples": fade_samples,
                    "fadeOutSamples": fade_samples,
                },
            }
        )
        audio_ops.extend(
            _resample_operation(
                ordinal, node_id, native_rate, sample_rate, sample_range
            )
        )
        if first:
            joins.append(first)
        protected_windows.extend(
            _protected_windows(
                snapshot, locator, start_time, end_time, first, last, fps, precise
            )
        )
    if not operations:
        raise ValueError("the canonical cut has no selected intervals")
    total_frames = operations[-1]["outputRange"]["endFrameExclusive"]
    total_samples = nodes[-1]["outputRange"]["endSampleExclusive"]
    audio_ops.append(
        {
            "operationId": "encode-program",
            "kind": "encode",
            "range": {"startSample": 0, "endSampleExclusive": total_samples},
            "parameters": {},
        }
    )
    radius = max(1, round(2 * fps))
    windows = [
        {
            "startFrame": max(0, join - radius),
            "endFrameExclusive": min(total_frames, join + radius),
        }
        for join in joins
    ]
    windows.extend(protected_windows)
    if len(protected_windows) != len(snapshot.get("protectedQuizWindows", [])):
        raise ValueError("every protected answer window must occur once in the cut")
    result = {
        "checkpoint": "cut-proof",
        "iterationId": iteration_id,
        "sourceFingerprints": fingerprints,
        "renderProfile": "cut-proof-360p",
        "output": {
            "path": str(output),
            "width": width,
            "height": height,
            "frameRate": frame_rate,
            "audioSampleRate": sample_rate,
            "channelLayout": "stereo",
            "videoCodec": "libx264",
            "audioCodec": "aac",
        },
        "videoGraph": {"operations": operations},
        "audioGraph": {
            "sampleRate": sample_rate,
            "nodes": nodes,
            "operations": audio_ops,
            "singleFinalEncode": True,
        },
        "events": [],
        "visionReviewPlanRef": None,
        "validationPlan": {
            "preflight": [
                "canonical-lock",
                "original-source-fingerprints",
                "audio-routing",
            ],
            "microproof": windows,
            "fullReview": ["transcript", "sequential-decode", "watch", "listening"],
            "historicalRegression": [],
        },
    }
    _bind_current_cutting(workspace, snapshot, frame_rate, result)
    return result


def _bind_current_cutting(workspace, snapshot, frame_rate, result):
    if not snapshot.get("cuttingRef"):
        return
    from .cutting_audit import audit_joins
    from .cutting_contracts import selection_graph_hash
    from .cutting_store import CuttingStore

    store = CuttingStore(
        Path(workspace.timeline_dir) / "cutting",
        video_id=workspace.video_id,
        provider=workspace.project["provider"],
    )
    document = store.load_document(snapshot["cuttingRef"])
    verified = document["payload"]
    if (
        document["documentType"] != "verification"
        or verified["status"] != "pass"
        or verified.get("graphHash") != selection_graph_hash(snapshot)
    ):
        raise ValueError("canonical cutting verification is missing or stale")
    result["validationPlan"]["cutting"] = {
        "required": True,
        "proposalRef": verified["proposalRef"],
        "verificationRef": snapshot["cuttingRef"],
        "graphHash": verified["graphHash"],
        "joinIds": [join["joinId"] for join in audit_joins(snapshot, frame_rate)],
    }
