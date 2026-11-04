"""Render declared absolute ProofPlan audio to lossless, sample-addressed PCM."""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.adapters.media.audio_tracks import (
    AudioGraphError,
    compile_continuous_audio_graph,
)
from avo.timeline.contracts import file_fingerprint, validate_document
from avo.timeline.event_clock import sample_rate_boundary


def _bounds(value):
    return value["startSample"], value["endSampleExclusive"]


def _native_lead_occupancy(value, frame_rate):
    """Validate retained source, then represent the native conformed PCM span.

    This is validation topology only. Original trim endpoints still reach the
    source resolver and native dialogue renderer without modification.
    """
    first, last = _bounds(value["sourceSampleRange"])
    expected = sample_rate_boundary(
        last, source_rate=value["sourceSampleRate"], target_rate=48000
    ) - sample_rate_boundary(
        first, source_rate=value["sourceSampleRate"], target_rate=48000
    )
    start, end = _bounds(value["outputSampleRange"])
    limit = Fraction(48000 * frame_rate[1], frame_rate[0])
    if abs(expected - (end - start)) > limit:
        raise AudioGraphError("Native dialogue conformance exceeds one video frame")
    retained = deepcopy(value)
    retained["outputSampleRange"] = {"startSample": 0, "endSampleExclusive": expected}
    compile_continuous_audio_graph(
        [retained],
        [
            {
                "kind": "encode",
                "range": {"startSample": 0, "endSampleExclusive": expected},
            }
        ],
        sample_rate=48000,
    )
    value["kind"] = "silence"
    return value


def _normalize_node(node, trims, lead_ids, frame_rate):
    if node["kind"] not in {"source", "music", "sfx", "ambience", "silence"}:
        raise AudioGraphError("Unsupported ProofPlan mix node kind")
    if node["latencyCompensationSamples"]:
        raise AudioGraphError("Mix latency reconciliation is not implemented")
    value = deepcopy(node)
    value["sourceSampleRange"] = value.pop("sourceRange")
    value["outputSampleRange"] = value.pop("outputRange")
    if node["kind"] != "silence":
        trim = trims.get(node["nodeId"])
        if trim is None or trim["range"] != node["outputRange"]:
            raise AudioGraphError("Missing exact audio source trim operation")
        value["kind"] = "source"
        source = trim["parameters"].get("source")
        value["input"] = (
            {"sha256": source["sha256"], "streamId": str(source["streamIndex"])}
            if isinstance(source, dict)
            else {"sha256": node["nodeId"], "streamId": "audio"}
        )
    if node["nodeId"] in lead_ids and node["kind"] == "source" and frame_rate:
        return _native_lead_occupancy(value, frame_rate)
    return value


def _trim_operations(operations):
    trims = {}
    for operation in operations:
        if operation["kind"] == "trim":
            node_id = operation["parameters"]["nodeId"]
            if node_id in trims:
                raise AudioGraphError("Duplicate audio trim operation")
            trims[node_id] = operation
    return trims


def _validate_mix_contract(graph, frame_rate):
    if graph.get("sampleRate") != 48000 or graph.get("singleFinalEncode") is not True:
        raise AudioGraphError("Proof mix requires 48000 Hz and one final encode")
    if frame_rate is not None and (
        len(frame_rate) != 2
        or any(type(value) is not int or value <= 0 for value in frame_rate)
    ):
        raise AudioGraphError("Native dialogue requires a positive rational frame rate")


def _prepare(graph, resolver, lead_ids=(), frame_rate=None):
    validate_document(graph, "avo.proof-plan.schema.json#/$defs/audioGraph")
    _validate_mix_contract(graph, frame_rate)
    operations = graph["operations"]
    trims = _trim_operations(operations)
    normalized = [
        _normalize_node(node, trims, lead_ids, frame_rate) for node in graph["nodes"]
    ]
    resolved = {}
    compiled = compile_continuous_audio_graph(normalized, operations, sample_rate=48000)
    for node in graph["nodes"]:
        if node["kind"] != "silence":
            # The executor owns original fingerprint, stream and ancestry admission.
            resolved[node["nodeId"]] = resolver(
                node, trims[node["nodeId"]]["parameters"]
            )
    expected = {n["nodeId"] for n in graph["nodes"] if n["kind"] != "silence"}
    if set(trims) != expected:
        raise AudioGraphError("Unconsumed audio trim operation")
    return compiled, resolved


def _validate_sidechains(params, node_id, nodes):
    sidechains = params.get("sidechainNodeIds", [])
    if not sidechains or set(sidechains) - set(nodes) or node_id in sidechains:
        raise AudioGraphError("Ducking requires known independent sidechain nodes")
    if len(sidechains) != len(set(sidechains)):
        raise AudioGraphError("Duplicate ducking sidechain")


def _validate_effect_values(kind, params, length):
    if kind == "gain":
        _number(params.get("gainDb"), -120, 30)
    elif kind == "duck":
        _number(params.get("attackMs", 20), 0.01, 2000)
        _number(params.get("releaseMs", 250), 0.01, 9000)
        _number(params.get("amountDb", 8), 1, 20)
    elif kind == "fade":
        for key in ("fadeInSamples", "fadeOutSamples"):
            count = params.get(key, 0)
            if type(count) is not int or not 0 <= count <= length:
                raise AudioGraphError("Fades require bounded integer sample counts")


def _validate_effect(operation, nodes, lead_ids, allowed):
    kind, params = operation["kind"], operation["parameters"]
    if kind not in allowed or set(params) - allowed[kind]:
        raise AudioGraphError(f"Unsupported mix operation or parameters: {kind}")
    node_id = params.get("nodeId")
    if node_id not in nodes or operation["range"] != nodes[node_id]["outputRange"]:
        raise AudioGraphError("Mix effects require one exact node output range")
    if node_id in lead_ids:
        raise AudioGraphError(
            "Ephemeral lead processing must be applied by its native renderer"
        )
    if kind == "duck":
        _validate_sidechains(params, node_id, nodes)
    first, last = _bounds(nodes[node_id]["outputRange"])
    _validate_effect_values(kind, params, last - first)
    return node_id


def _effects(graph, lead_ids):
    nodes = {n["nodeId"]: n for n in graph["nodes"]}
    effects = {key: {} for key in nodes}
    allowed = {
        "gain": {"nodeId", "gainDb"},
        "fade": {"nodeId", "fadeInSamples", "fadeOutSamples"},
        "duck": {"nodeId", "sidechainNodeIds", "amountDb", "attackMs", "releaseMs"},
    }
    for operation in graph["operations"]:
        kind, params = operation["kind"], operation["parameters"]
        if kind in {"trim", "resample", "mix", "encode"}:
            continue
        node_id = _validate_effect(operation, nodes, lead_ids, allowed)
        if kind in effects[node_id]:
            raise AudioGraphError(f"Duplicate {kind} operation for {node_id}")
        effects[node_id][kind] = params
    _trim_fades(graph, effects, lead_ids)
    return effects


def _trim_fades(graph, effects, lead_ids):
    allowed = {
        "nodeId",
        "sourceId",
        "source",
        "fadeInSamples",
        "fadeOutSamples",
        "dialogueNoiseReductionPolicy",
        "dialogueTreatmentPolicy",
    }
    for operation in graph["operations"]:
        if operation["kind"] != "trim":
            continue
        params = operation["parameters"]
        node_id = params["nodeId"]
        if set(params) - allowed:
            raise AudioGraphError("Unsupported source trim parameters in audio mix")
        if node_id in lead_ids:
            continue
        if {"dialogueNoiseReductionPolicy", "dialogueTreatmentPolicy"} & set(params):
            raise AudioGraphError(
                "Dialogue treatment cannot process music, SFX or ambience"
            )
        fade = {key: params.get(key, 0) for key in ("fadeInSamples", "fadeOutSamples")}
        if not any(fade.values()):
            continue
        first, last = _bounds(operation["range"])
        _validate_effect_values("fade", fade, last - first)
        if "fade" in effects[node_id]:
            raise AudioGraphError("Fades must be declared once per audio node")
        effects[node_id]["fade"] = fade


def validate_proof_audio_mix(
    audio_graph, *, source_resolver, lead_node_ids=None, lead_frame_rate=None
):
    """Fail before media creation on graph, routing or source admission errors."""
    lead_ids = set(lead_node_ids or ())
    compiled, _ = _prepare(audio_graph, source_resolver, lead_ids, lead_frame_rate)
    nodes = {node["nodeId"]: node for node in audio_graph["nodes"]}
    if lead_ids - set(nodes) or any(
        nodes[key]["kind"] not in {"source", "silence"} for key in lead_ids
    ):
        raise AudioGraphError(
            "Ephemeral lead requires known dialogue or silence node IDs"
        )
    _effects(audio_graph, lead_ids)
    return compiled


def _number(value, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise AudioGraphError("Audio parameter must be numeric") from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise AudioGraphError("Audio parameter is outside its supported range")
    return value


def _input_routes(resolved, lead_ids, lead_pcm, lead_pcm_start_sample, total, first):
    inputs, filters, labels = [], [], {}
    routes = {}
    for node_id, (path, stream) in resolved.items():
        if node_id in lead_ids:
            continue
        key = (str(Path(path)), int(stream))
        routes.setdefault(key, []).append(node_id)
    for index, ((path, stream), ids) in enumerate(routes.items()):
        inputs.extend(["-i", path])
        names = [f"src{len(labels) + i}" for i in range(len(ids))]
        source = f"[{index}:{stream}]"
        filters.append(source + f"asplit={len(ids)}" + "".join(f"[{n}]" for n in names))
        labels.update(zip(ids, names))
    lead_label = None
    if lead_pcm:
        index = len(routes)
        inputs.extend(["-i", str(lead_pcm)])
        lead_label = "lead"
        filters.append(
            f"[{index}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=start_sample={first - lead_pcm_start_sample}:end_sample={first - lead_pcm_start_sample + total},"
            f"asetpts=PTS-STARTPTS,"
            f"atrim=end_sample={total}[lead]"
        )

    return inputs, filters, labels, lead_label


def _pcm_samples(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    return (
        int(stream["sample_rate"]),
        int(stream["channels"]),
        int(stream["duration_ts"]),
    )


def _stage_source(node, source, path):
    first, last = _bounds(node["sourceRange"])
    mapping = node["channelMap"]
    expected = (
        node["outputRange"]["endSampleExclusive"] - node["outputRange"]["startSample"]
    )
    filters = (
        f"atrim=start_sample={first}:end_sample={last},asetpts=PTS-STARTPTS,"
        "ashowinfo@retained,aresample=48000,ashowinfo@resampled,"
        f"pan=stereo|c0=c{mapping[0]}|c1=c{mapping[1]},atrim=end_sample={expected}"
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(source[0]),
            "-map",
            f"0:{source[1]}",
            "-af",
            filters,
            "-c:a",
            "pcm_f32le",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AudioGraphError(
            "Finite source extraction failed: " + result.stderr[-2000:]
        )
    _validate_staged_counts(result.stderr, node, expected)
    if _pcm_samples(path) != (48000, 2, expected):
        raise AudioGraphError(
            "Audio source range exceeds decoded EOF or sample contract"
        )


def _validate_staged_counts(log, node, expected):
    def count(label):
        return sum(
            int(value) for value in re.findall(label + r"[^\n]*nb_samples:(\d+)", log)
        )

    first, last = _bounds(node["sourceRange"])
    if count("ashowinfo@retained") != last - first:
        raise AudioGraphError("Audio source range exceeds decoded EOF at native rate")
    produced = count("ashowinfo@resampled")
    surplus = 1 if node["sourceSampleRate"] != 48000 else 0
    if not expected <= produced <= expected + surplus:
        raise AudioGraphError("Resampled source differs from endpoint sample contract")


def _stage_sources(nodes, resolved, lead_ids, directory, first, last):
    retained, staged, cache = deepcopy(nodes), {}, {}
    for node_id, source in resolved.items():
        node = retained[node_id]
        a, b = _bounds(node["outputRange"])
        if node_id in lead_ids or b <= first or a >= last:
            continue
        key = (source, tuple(node["sourceRange"].values()), tuple(node["channelMap"]))
        if key not in cache:
            path = Path(directory) / f"source-{len(cache)}.wav"
            _stage_source(node, source, path)
            cache[key] = path
        staged[node_id] = (cache[key], 0)
        node["sourceRange"] = {"startSample": 0, "endSampleExclusive": b - a}
        node["channelMap"] = [0, 1]
        node["sourceSampleRate"] = 48000
    return retained, staged


def _validate_lead(lead_pcm, start, first, last):
    if lead_pcm is None:
        return
    rate, channels, count = _pcm_samples(lead_pcm)
    if (rate, channels) != (48000, 2) or start > first or start + count < last:
        raise AudioGraphError(
            "Ephemeral lead PCM does not cover the exact requested window"
        )


def _node_chain(node_id, node, ordinal, labels, effects, first, last):
    start, end = _bounds(node["outputRange"])
    length = end - start
    label = f"n{ordinal}"
    if node["kind"] == "silence":
        chain = "anullsrc=r=48000:cl=stereo," + f"atrim=end_sample={length}"
    else:
        a, b = _bounds(node["sourceRange"])
        mapping = node["channelMap"]
        if len(mapping) != 2:
            raise AudioGraphError("Proof mix requires stereo target mapping")
        chain = f"[{labels[node_id]}]atrim=start_sample={a}:end_sample={b},asetpts=PTS-STARTPTS"
        chain += f",aresample=48000,pan=stereo|c0=c{mapping[0]}|c1=c{mapping[1]}"
        gain = effects[node_id].get("gain", {})
        if gain:
            chain += f",volume={_number(gain['gainDb'], -120, 30)}dB"
        fade = effects[node_id].get("fade", {})
        for key, direction in [("fadeInSamples", "in"), ("fadeOutSamples", "out")]:
            count = fade.get(key, 0)
            if type(count) is not int or not 0 <= count <= length:
                raise AudioGraphError("Fades require bounded integer sample counts")
            if count:
                position = 0 if direction == "in" else length - count
                chain += f",afade=t={direction}:ss={position}:ns={count}"
    chain += (
        f",atrim=start_sample={max(0, first - start)}:end_sample={min(length, last - start)},"
        "asetpts=PTS-STARTPTS"
    )
    delay = max(0, start - first)
    if delay:
        # adelay allocates a delay-sized ring per source. Hundreds of late
        # finite cues would reserve program-length buffers. A lazy, exact PCM
        # silence prefix represents the same clock with bounded frame memory.
        chain += (
            f"[content{ordinal}];anullsrc=r=48000:cl=stereo,"
            f"atrim=end_sample={delay}[prefix{ordinal}];"
            f"[prefix{ordinal}][content{ordinal}]concat=n=2:v=0:a=1[{label}]"
        )
    else:
        chain += f"[{label}]"
    return label, chain


def _render_nodes(nodes, lead_ids, labels, effects, first, last, filters, lead_label):
    rendered = {}
    for ordinal, (node_id, node) in enumerate(nodes.items()):
        a, b = _bounds(node["outputRange"])
        if node_id in lead_ids or b <= first or a >= last:
            continue
        label, chain = _node_chain(node_id, node, ordinal, labels, effects, first, last)
        filters.append(chain)
        rendered[node_id] = label
    if lead_label:
        for node_id in lead_ids:
            rendered[node_id] = lead_label

    return rendered


def _sidechain_routes(effects, rendered, consumers):
    duck_sides = {}
    for node_id, effect in effects.items():
        if "duck" not in effect:
            continue
        names = list(
            dict.fromkeys(rendered[n] for n in effect["duck"]["sidechainNodeIds"])
        )
        duck_sides[node_id] = []
        for name in names:
            target = f"sc{len(duck_sides)}x{len(duck_sides[node_id])}"
            consumers[name].append(target)
            duck_sides[node_id].append(target)
    return duck_sides


def _missing_sidechain_silence(effects, rendered, filters, count):
    needed = {
        key
        for value in effects.values()
        for key in value.get("duck", {}).get("sidechainNodeIds", [])
    }
    for key in sorted(needed - set(rendered)):
        label = f"quiet{len(rendered)}"
        filters.append(f"anullsrc=r=48000:cl=stereo,atrim=end_sample={count}[{label}]")
        rendered[key] = label


def _mix_filters(rendered, effects, filters, first, last):
    effects = {key: value for key, value in effects.items() if key in rendered}
    _missing_sidechain_silence(effects, rendered, filters, last - first)
    # Split each materialized stream once for all mix/sidechain consumers.
    mix_names = list(dict.fromkeys(rendered.values()))
    consumers = {name: [name + "mix"] for name in mix_names}
    duck_sides = _sidechain_routes(effects, rendered, consumers)
    for name, targets in consumers.items():
        # Keep finite-input EOF beyond the requested window while sidechain
        # consumers drain. The final trim removes this verified-silence guard.
        filters.append(
            f"[{name}]apad=whole_len={last - first + 48000},asplit={len(targets)}"
            + "".join(f"[{t}]" for t in targets)
        )
    for ordinal, (node_id, side_labels) in enumerate(duck_sides.items()):
        params = effects[node_id]["duck"]
        side = f"side{ordinal}"
        filters.append(
            "".join(f"[{x}]" for x in side_labels)
            + f"amix=inputs={len(side_labels)}:normalize=0[{side}]"
        )
        label = rendered[node_id] + "mix"
        attack = _number(params.get("attackMs", 20), 0.01, 2000)
        release = _number(params.get("releaseMs", 250), 0.01, 9000)
        ratio = _number(params.get("amountDb", 8), 1, 20)
        filters.append(
            f"[{label}][{side}]sidechaincompress=threshold=0.05:ratio={ratio}:attack={attack}:release={release}[duck{ordinal}]"
        )
        mix_names[mix_names.index(rendered[node_id])] = f"duck{ordinal}"
    final = [f"[{n}]" if n.startswith("duck") else f"[{n}mix]" for n in mix_names]
    filters.append(
        "".join(final)
        + f"amix=inputs={len(final)}:duration=longest:normalize=0:dropout_transition=0,"
        f"atrim=start_sample={first}:end_sample={last},asetpts=PTS-STARTPTS,"
        "astats=metadata=0:reset=0[out]"
    )


def _write_pcm(output, inputs, filters, sample_count):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="proof-mix-", dir=output.parent
    ) as directory:
        script = Path(directory) / "mix.ffgraph"
        script.write_text(";\n".join(filters), encoding="utf-8")
        candidate = Path(directory) / "mix.wav"
        command = [
            "ffmpeg",
            "-v",
            "info",
            "-nostats",
            *inputs,
            "-filter_complex_script",
            str(script),
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-c:a",
            "pcm_f32le",
            "-rf64",
            "auto",
            str(candidate),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise AudioGraphError("Proof PCM mix failed: " + result.stderr[-4000:])
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(candidate)],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        observed = (
            int(stream["sample_rate"]),
            int(stream["channels"]),
            int(stream["duration_ts"]),
        )
        if observed != (48000, 2, sample_count):
            raise AudioGraphError(f"Proof PCM sample contract mismatch: {observed}")
        candidate.replace(output)
    return {
        "peakDbfs": _astats_value(result.stderr, "Peak level dB"),
        "rmsDbfs": _astats_value(result.stderr, "RMS level dB"),
    }


def _astats_value(log, field):
    values = re.findall(re.escape(field) + r":\s*([-+\w.]+)", log)
    if not values:
        raise AudioGraphError("PCM mix measurement missing: " + field)
    value = float(values[-1])
    return value if math.isfinite(value) else None


def _validate_window(first, last, total, lead_pcm_start_sample):
    if not (
        isinstance(first, int) and isinstance(last, int) and 0 <= first < last <= total
    ):
        raise AudioGraphError("Invalid sample window")
    if type(lead_pcm_start_sample) is not int or not 0 <= lead_pcm_start_sample < total:
        raise AudioGraphError("Invalid ephemeral lead sample origin")


def render_proof_audio_mix(
    audio_graph,
    output: Path,
    *,
    source_resolver,
    lead_pcm: Path | None = None,
    lead_node_ids: set[str] | None = None,
    window: tuple[int, int] | None = None,
    lead_pcm_start_sample: int = 0,
    lead_frame_rate: tuple[int, int] | None = None,
):
    """Mix finite nodes; resolver must validate originals and declared source ranges.

    lead_pcm, when supplied, is the executor's ephemeral same-plan full dialogue
    concat, never a prior proof/export. Its originals still pass source_resolver.
    Effects target whole node ranges. Loops must already be expanded by AVO.
    """
    lead_ids = set(lead_node_ids or ())
    compiled, resolved = _prepare(
        audio_graph, source_resolver, lead_ids, lead_frame_rate
    )
    admitted_source_ids = sorted(resolved)
    nodes = {n["nodeId"]: n for n in audio_graph["nodes"]}
    if bool(lead_pcm) != bool(lead_ids) or lead_ids - set(nodes):
        raise AudioGraphError("Ephemeral lead requires exact known source node IDs")
    effects = _effects(audio_graph, lead_ids)
    total = compiled["durationSamples"]
    first, last = window or (0, total)
    _validate_window(first, last, total, lead_pcm_start_sample)
    _validate_lead(lead_pcm, lead_pcm_start_sample, first, last)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="proof-sources-", dir=output.parent
    ) as directory:
        nodes, resolved = _stage_sources(
            nodes, resolved, lead_ids, directory, first, last
        )
        inputs, filters, labels, lead_label = _input_routes(
            resolved, lead_ids, lead_pcm, lead_pcm_start_sample, last - first, first
        )
        rendered = _render_nodes(
            nodes, lead_ids, labels, effects, first, last, filters, lead_label
        )
        _mix_filters(rendered, effects, filters, 0, last - first)
        output = Path(output)
        measurement = _write_pcm(output, inputs, filters, last - first)
    return {
        "output": file_fingerprint(output),
        "sampleRate": 48000,
        "channels": 2,
        "sampleCount": last - first,
        "window": {"startSample": first, "endSampleExclusive": last},
        "audioEncodeCount": 0,
        "pcmCodec": "pcm_f32le",
        "measurement": measurement,
        "graphHash": compiled["graphHash"],
        "sourceNodeIds": admitted_source_ids,
        "ephemeralLeadNodeIds": sorted(lead_ids),
    }
