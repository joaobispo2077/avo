"""Keep source-cut dialogue and declared absolute mix events on one proof clock."""

import subprocess
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.timeline.event_clock import (
    EventClockError,
    frame_to_sample,
    sample_rate_boundary,
)

MIX_KINDS = frozenset({"music", "sfx", "ambience"})


def _transient_offset(event, node, rate):
    value = event.get("transientOffset")
    if value is None:
        return 0
    allowed = {"sourceSamples", "sourceRate", "resolvedOutputSamples"}
    if event["role"] != "sfx" or not isinstance(value, dict) or set(value) - allowed:
        raise RuntimeError("ProofPlan transient requires a declared SFX source offset")
    if value.get("sourceRate") != node["sourceSampleRate"]:
        raise RuntimeError("ProofPlan transient source rate differs from its node")
    try:
        offset = sample_rate_boundary(
            value.get("sourceSamples"),
            source_rate=value.get("sourceRate"),
            target_rate=rate,
        )
    except EventClockError as error:
        raise RuntimeError("Invalid ProofPlan transient clock") from error
    if value.get("resolvedOutputSamples", offset) != offset:
        raise RuntimeError("ProofPlan transient offset differs from its sample clock")
    source = node["sourceRange"]
    if value["sourceSamples"] >= source["endSampleExclusive"] - source["startSample"]:
        raise RuntimeError("ProofPlan transient lies outside its retained source")
    return offset


def _validate_event_clock(event, node, fps, rate):
    start = node["outputRange"]["startSample"]
    expected = frame_to_sample(
        event["programFrame"],
        frame_rate_num=fps.numerator,
        frame_rate_den=fps.denominator,
        sample_rate=rate,
    )
    offset = _transient_offset(event, node, rate)
    if (
        event.get("visibleRange") is not None
        or event.get("sourceRange") != node["sourceRange"]
        or event.get("resolvedImpactSample") != expected
        or expected - offset != start
        or event.get("entryEffectIds")
    ):
        raise RuntimeError("ProofPlan audio event differs from its frozen node clock")
    if event["role"] != "source-audio" and event["role"] != node["kind"]:
        raise RuntimeError("ProofPlan audio event role differs from its node")


def validate_audio_events(execution):
    nodes = {
        node["nodeId"]: node
        for node in execution["audioGraph"]["nodes"]
        if node["kind"] in MIX_KINDS
    }
    handled, linked = set(), set()
    fps = Fraction(**_fraction_args(execution["output"]["frameRate"]))
    rate = execution["audioGraph"]["sampleRate"]
    for event in execution["events"]:
        audio = event.get("audio")
        if event.get("role") not in MIX_KINDS | {"source-audio"}:
            continue
        if not isinstance(audio, dict) or set(audio) != {"nodeId"}:
            raise RuntimeError("ProofPlan audio event requires one declared node")
        node = nodes.get(audio["nodeId"])
        if node is None or node["nodeId"] in linked:
            raise RuntimeError("ProofPlan audio event node is missing or duplicated")
        _validate_event_clock(event, node, fps, rate)
        handled.add(event["eventId"])
        linked.add(node["nodeId"])
    if linked != set(nodes):
        raise RuntimeError("ProofPlan mix nodes require explicit matching audio events")
    return handled


def _fraction_args(value):
    return {"numerator": value["num"], "denominator": value["den"]}


def _lead_operation(operation, lead_ids):
    if operation["kind"] == "encode":
        return True
    return (
        operation["kind"] in {"trim", "resample"}
        and operation["parameters"]["nodeId"] in lead_ids
    )


def prepare_mix(execution, source_resolver):
    if not any(n["kind"] in MIX_KINDS for n in execution["audioGraph"]["nodes"]):
        return execution, None
    from .proof_audio_mix import validate_proof_audio_mix

    graph = execution["audioGraph"]
    lead_ids = {n["nodeId"] for n in graph["nodes"] if n["kind"] not in MIX_KINDS}
    clock = execution["output"]["frameRate"]
    frame_rate = (clock["num"], clock["den"])
    validate_proof_audio_mix(
        graph,
        source_resolver=source_resolver,
        lead_node_ids=lead_ids,
        lead_frame_rate=frame_rate,
    )
    lead = deepcopy(execution)
    lead["audioGraph"]["nodes"] = [n for n in graph["nodes"] if n["nodeId"] in lead_ids]
    lead["audioGraph"]["operations"] = [
        op for op in graph["operations"] if _lead_operation(op, lead_ids)
    ]
    return lead, {
        "graph": graph,
        "resolver": source_resolver,
        "leadIds": lead_ids,
        "frameRate": frame_rate,
    }


def render_mix(listing, directory, context, *, start_sample, end_sample):
    from .proof_audio_mix import render_proof_audio_mix

    lead = Path(directory) / "dialogue-native.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s32le",
            str(lead),
        ],
        check=True,
        capture_output=True,
    )
    output = Path(directory) / "program-mix.wav"
    context["result"] = render_proof_audio_mix(
        context["graph"],
        output,
        source_resolver=context["resolver"],
        lead_pcm=lead,
        lead_node_ids=context["leadIds"],
        lead_frame_rate=context["frameRate"],
        lead_pcm_start_sample=start_sample,
        window=(start_sample, end_sample),
    )
    return output
