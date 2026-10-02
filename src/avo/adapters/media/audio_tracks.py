"""Compile inspectable audio Tracks into an ffmpeg filter graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from avo.timeline.contracts import content_hash
from avo.timeline.event_clock import sample_rate_boundary


class AudioGraphError(ValueError):
    """Raised when continuous PCM placement would be ambiguous or lossy."""


_CHANNEL_COUNTS = {"mono": 1, "stereo": 2}
_OPERATION_KINDS = {
    "mix",
    "crossfade",
    "gain",
    "fade",
    "duck",
    "filter",
    "resample",
    "pad",
    "trim",
    "time-stretch",
    "drift-correction",
    "encode",
}


def _sample_range(value: dict[str, Any], label: str) -> tuple[int, int]:
    try:
        start = int(value["startSample"])
        end = int(value["endSampleExclusive"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AudioGraphError(f"{label} requires exact sample boundaries") from exc
    if start < 0 or end <= start:
        raise AudioGraphError(f"{label} must be a non-empty half-open range")
    return start, end


def _operation_covering(
    operations: list[dict[str, Any]],
    *,
    kinds: set[str],
    start: int,
    end: int,
) -> dict[str, Any] | None:
    for operation in operations:
        if operation.get("kind") not in kinds:
            continue
        op_start, op_end = _sample_range(operation.get("range") or {}, "operation")
        if op_start <= start and op_end >= end:
            return operation
    return None


def compile_continuous_audio_graph(
    nodes: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    *,
    sample_rate: int = 48_000,
) -> dict[str, Any]:
    """Validate and freeze one absolute, continuous PCM-domain audio graph.

    Source endpoints are converted once from their native rate. Gaps require an
    explicit silence node, overlaps require mix/crossfade, and non-zero decoder
    or filter latency requires a named approved reconciliation operation.
    """
    if sample_rate <= 0:
        raise AudioGraphError("target sample rate must be positive")
    if not nodes:
        raise AudioGraphError("audio graph requires at least one node")
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for raw in nodes:
        node = deepcopy(raw)
        node_id = str(node.get("nodeId") or "")
        if not node_id or node_id in identities:
            raise AudioGraphError("audio node IDs must be unique and stable")
        identities.add(node_id)
        target_rate = int(node.get("targetSampleRate") or sample_rate)
        if target_rate != sample_rate:
            raise AudioGraphError(f"target sample rate mismatch: {node_id}")
        output_start, output_end = _sample_range(
            node.get("outputSampleRange") or {}, f"output range for {node_id}"
        )
        if not node.get("channelMap"):
            raise AudioGraphError(f"channel map is required: {node_id}")
        source_channels = _CHANNEL_COUNTS.get(str(node.get("sourceLayout")))
        target_channels = _CHANNEL_COUNTS.get(str(node.get("targetLayout")))
        mapping = node["channelMap"]
        if target_channels is None or len(mapping) != target_channels:
            raise AudioGraphError(
                f"channel map does not match target layout: {node_id}"
            )
        if node.get("kind") == "source" and (
            source_channels is None
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                or value >= source_channels
                for value in mapping
            )
        ):
            raise AudioGraphError(
                f"channel map references missing source channel: {node_id}"
            )
        if node.get("kind") == "source":
            source_start, source_end = _sample_range(
                node.get("sourceSampleRange") or {}, f"source range for {node_id}"
            )
            source_rate = int(node.get("sourceSampleRate") or 0)
            expected = sample_rate_boundary(
                source_end, source_rate=source_rate, target_rate=sample_rate
            ) - sample_rate_boundary(
                source_start, source_rate=source_rate, target_rate=sample_rate
            )
            if output_end - output_start != expected:
                raise AudioGraphError(
                    f"target length mismatch for {node_id}: expected {expected}"
                )
            latency = sum(
                int((node.get("latency") or {}).get(key) or 0)
                for key in ("decoderSamples", "resamplerSamples", "filterSamples")
            )
            if latency:
                declared_compensation = node.get("latencyCompensationSamples")
                reconciliation = _operation_covering(
                    operations,
                    kinds={"pad", "trim", "time-stretch", "drift-correction"},
                    start=output_start,
                    end=output_end,
                )
                parameters = (reconciliation or {}).get("parameters") or {}
                compensated = (
                    declared_compensation is not None
                    and int(declared_compensation) == latency
                )
                if not compensated and (
                    not reconciliation
                    or not parameters.get("approved")
                    or parameters.get("nodeId") != node_id
                ):
                    raise AudioGraphError(
                        f"uncompensated latency for {node_id}: {latency} samples"
                    )
            node["expectedTargetSamples"] = expected
            node["latencySamples"] = latency
        elif node.get("kind") != "silence":
            raise AudioGraphError(f"unsupported PCM node kind: {node.get('kind')}")
        normalized.append(node)

    normalized.sort(
        key=lambda item: (
            int(item["outputSampleRange"]["startSample"]),
            int(item["outputSampleRange"]["endSampleExclusive"]),
            str(item["nodeId"]),
        )
    )
    for operation in operations:
        kind = str(operation.get("kind") or "")
        if kind not in _OPERATION_KINDS:
            raise AudioGraphError(f"unsupported audio operation: {kind}")
        _sample_range(operation.get("range") or {}, f"{kind} operation")
    cursor = 0
    overlaps: list[dict[str, Any]] = []
    for node in normalized:
        start, end = _sample_range(node["outputSampleRange"], "output range")
        if start > cursor:
            raise AudioGraphError(f"unexplained audio gap [{cursor},{start})")
        if start < cursor:
            overlap_end = min(cursor, end)
            operation = _operation_covering(
                operations,
                kinds={"mix", "crossfade"},
                start=start,
                end=overlap_end,
            )
            if operation is None:
                raise AudioGraphError(
                    f"unexplained audio overlap [{start},{overlap_end})"
                )
            overlaps.append(
                {
                    "startSample": start,
                    "endSampleExclusive": overlap_end,
                    "operationId": operation["operationId"],
                }
            )
        cursor = max(cursor, end)

    encodes = [item for item in operations if item.get("kind") == "encode"]
    if len(encodes) != 1:
        raise AudioGraphError("audio graph requires exactly one final encode")
    encode_start, encode_end = _sample_range(encodes[0].get("range") or {}, "encode")
    if (encode_start, encode_end) != (0, cursor):
        raise AudioGraphError("final encode must cover the complete PCM program")
    body = {
        "schemaVersion": "1.0.0",
        "sampleRate": sample_rate,
        "nodes": normalized,
        "operations": deepcopy(operations),
        "durationSamples": cursor,
        "overlaps": overlaps,
        "singleFinalEncode": True,
        "decodeKeys": sorted(
            {
                f"{node['input']['sha256']}:{node['input']['streamId']}"
                for node in normalized
                if node.get("kind") == "source"
            }
        ),
    }
    return {**body, "graphHash": content_hash(body)}


def _seconds(ticks: int, timebase: dict[str, int] | None = None) -> float:
    num = int((timebase or {}).get("num", 1))
    den = int((timebase or {}).get("den", 1000))
    return float(ticks) * num / den


def _ducking_filter(label: str, sidechain: str, ducking: dict, end: float) -> str:
    end_sample = round(end * 48000)
    if end_sample <= 0:
        raise AudioGraphError("ducked audio requires a positive region end")
    attack = float(ducking.get("attackMs") or 20)
    release = float(ducking.get("releaseMs") or 250)
    amount = float(ducking.get("amountDb") or 8)
    # Do not let either input's EOF discard the compressor's queued samples.
    # Silence padding is bounded by the declared absolute timeline end.
    return (
        f"[{label}]apad[{label}pad];[{sidechain}]apad[{sidechain}pad];"
        f"[{label}pad][{sidechain}pad]sidechaincompress="
        f"threshold=0.05:ratio={max(1.0, amount)}:attack={attack}:release={release},"
        f"atrim=end_sample={end_sample}[{label}d]"
    )


def compile_audio_layers(
    layers: list[dict[str, Any]],
    *,
    first_input_index: int = 1,
) -> dict[str, Any]:
    """Compile dialogue, music beds, SFX, and ambience with ducking and fades."""
    ordered = sorted(
        layers, key=lambda item: (item.get("order", 0), item.get("layerId", ""))
    )
    ducking_count = sum(
        1
        for layer in ordered
        if not layer.get("mute")
        and layer.get("ducking")
        and layer.get("role") != "dialogue"
    )
    filters: list[str] = []
    inputs: list[str] = []
    trace: list[dict[str, Any]] = []
    mix_labels: list[str] = []
    sidechain_pads: list[str] = []
    input_index = first_input_index

    for layer in ordered:
        role = str(layer.get("role") or "")
        enabled = not bool(layer.get("mute"))
        trace.append(
            {
                "layerId": layer.get("layerId"),
                "role": role,
                "enabled": enabled,
                "order": layer.get("order", 0),
            }
        )
        if not enabled:
            continue
        locator = str((layer.get("source") or {}).get("locator") or "")
        inputs.append(locator)
        region = (layer.get("regions") or [{}])[0]
        start = _seconds(int(region.get("startTicks") or 0), region.get("timebase"))
        end = _seconds(int(region.get("endTicks") or 0), region.get("timebase"))
        duration = max(0.0, end - start)
        gain = float(layer.get("gainDb") or 0)
        label = f"a{layer.get('layerId')}"
        parts = [f"[{input_index}:a]aformat=sample_rates=48000:channel_layouts=stereo"]
        if gain:
            parts.append(f"volume={gain:.3f}dB")
        if role != "dialogue":
            delay_ms = max(0, round(start * 1000))
            parts.append(f"adelay={delay_ms}|{delay_ms}")
        fades = layer.get("fades") or {}
        in_ticks = int(fades.get("inTicks") or 0)
        out_ticks = int(fades.get("outTicks") or 0)
        if in_ticks:
            parts.append(f"afade=t=in:st=0:d={_seconds(in_ticks):.3f}")
        if out_ticks and duration > 0:
            fade_out = _seconds(out_ticks)
            parts.append(
                f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}"
            )
        filters.append(",".join(parts) + f"[{label}]")
        if role == "dialogue" and ducking_count:
            pads = "".join(f"[dlgsc{index}]" for index in range(ducking_count))
            filters.append(f"[{label}]asplit={ducking_count + 1}[dlgmix]{pads}")
            mix_labels.append("[dlgmix]")
            sidechain_pads = [f"dlgsc{index}" for index in range(ducking_count)]
        elif role == "dialogue":
            mix_labels.append(f"[{label}]")
        else:
            ducking = layer.get("ducking") or {}
            if ducking and sidechain_pads:
                ducked = f"{label}d"
                sidechain = sidechain_pads.pop(0)
                filters.append(_ducking_filter(label, sidechain, ducking, end))
                mix_labels.append(f"[{ducked}]")
            else:
                mix_labels.append(f"[{label}]")
        input_index += 1

    if mix_labels:
        filters.append(
            "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0:"
            "normalize=0[outa]"
        )
    return {
        "filters": filters,
        "inputs": inputs,
        "outputLabel": "[outa]",
        "trace": trace,
    }
