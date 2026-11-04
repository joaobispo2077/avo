"""Rebuild declared beds around independently extracted original dialogue."""

from pathlib import Path

from avo.adapters.media.proof_audio_bridge import MIX_KINDS
from avo.adapters.media.proof_audio_mix import render_proof_audio_mix
from avo.adapters.media.proof_executor import _source
from avo.timeline.event_clock import frame_to_sample


def mix_reference_context(plan, window):
    if not any(
        node["kind"] in MIX_KINDS
        for node in plan.get("audioGraph", {}).get("nodes", [])
    ):
        return None
    return {"plan": plan, "window": window}


def render_mixed_reference(lead, output, context):
    """Use original-source admission and the frozen graph, never candidate PCM."""
    plan, window = context["plan"], context["window"]
    fps = plan["output"]["frameRate"]
    first, last = (
        frame_to_sample(
            window[key],
            frame_rate_num=fps["num"],
            frame_rate_den=fps["den"],
            sample_rate=48000,
        )
        for key in ("startFrame", "endFrameExclusive")
    )
    graph = plan["audioGraph"]
    lead_ids = {n["nodeId"] for n in graph["nodes"] if n["kind"] not in MIX_KINDS}
    cache = {}
    render_proof_audio_mix(
        graph,
        Path(output),
        source_resolver=lambda node, parameters: _source(
            parameters, plan["canonicalInputLock"], cache, audio_node=node
        ),
        lead_pcm=Path(lead),
        lead_node_ids=lead_ids,
        lead_frame_rate=(fps["num"], fps["den"]),
        lead_pcm_start_sample=first,
        window=(first, last),
    )
    return Path(output)
