"""Compile inspectable audio Tracks into an ffmpeg filter graph."""

from __future__ import annotations

from typing import Any


def _seconds(ticks: int, timebase: dict[str, int] | None = None) -> float:
    num = int((timebase or {}).get("num", 1))
    den = int((timebase or {}).get("den", 1000))
    return float(ticks) * num / den


def compile_audio_layers(
    layers: list[dict[str, Any]],
    *,
    first_input_index: int = 1,
) -> dict[str, Any]:
    """Compile dialogue, music beds, SFX, and ambience with ducking and fades."""
    ordered = sorted(layers, key=lambda item: (item.get("order", 0), item.get("layerId", "")))
    ducking_count = sum(
        1
        for layer in ordered
        if not layer.get("mute") and layer.get("ducking") and layer.get("role") != "dialogue"
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
            delay_ms = max(0, int(round(start * 1000)))
            parts.append(f"adelay={delay_ms}|{delay_ms}")
        fades = layer.get("fades") or {}
        in_ticks = int(fades.get("inTicks") or 0)
        out_ticks = int(fades.get("outTicks") or 0)
        if in_ticks:
            parts.append(f"afade=t=in:st=0:d={_seconds(in_ticks):.3f}")
        if out_ticks and duration > 0:
            fade_out = _seconds(out_ticks)
            parts.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}")
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
                attack = float(ducking.get("attackMs") or 20)
                release = float(ducking.get("releaseMs") or 250)
                amount = float(ducking.get("amountDb") or 8)
                sidechain = sidechain_pads.pop(0)
                filters.append(
                    f"[{label}][{sidechain}]sidechaincompress="
                    f"threshold=0.05:ratio={max(1.0, amount)}:attack={attack}:release={release}"
                    f"[{ducked}]"
                )
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
