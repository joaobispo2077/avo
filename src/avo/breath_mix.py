"""Freeze the unchanged mix, then subtract only the selected dialogue delta.

Two passes avoid FFmpeg framesync/EOF changes when a new dialogue filter is
inserted in a live sidechain graph. Music, SFX and their control signals never
pass through breath processing. Inputs must already have canonical lineage.
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import numpy as np

from avo.breath_control import BreathControlError, apply_control, resolve_control
from avo.timeline.contracts import content_hash, file_fingerprint, validate_document


def correct_frozen_mix(
    mix: np.ndarray, dialogue: np.ndarray, control: dict, rate: int = 48000
) -> tuple[np.ndarray, np.ndarray]:
    """Use the identical pre-normalization dialogue contribution, not a master."""
    if mix.ndim != dialogue.ndim or mix.shape[1:] != dialogue.shape[1:]:
        raise BreathControlError("frozen mix and dialogue channel layouts differ")
    if len(dialogue) > len(mix) or not np.isfinite(mix).all():
        raise BreathControlError("frozen mix has invalid samples or duration")
    _, removed = apply_control(dialogue, control, rate)
    delta = np.zeros_like(mix)
    delta[: len(removed)] = removed
    output = mix.copy()
    active = np.any(delta != 0, axis=1) if delta.ndim == 2 else delta != 0
    output[active] -= delta[active]
    return output, delta


def _render_pcm(layers: list[dict], path: Path) -> np.ndarray:
    from avo.adapters.media.audio_tracks import compile_audio_layers

    compiled = compile_audio_layers(layers, first_input_index=0)
    command = ["ffmpeg", "-v", "error", "-n"]
    for source in compiled["inputs"]:
        command += ["-i", source]
    command += [
        "-filter_complex",
        ";".join(compiled["filters"]),
        "-map",
        compiled["outputLabel"],
        "-f",
        "f32le",
        str(path),
    ]
    subprocess.run(command, capture_output=True, check=True)
    return np.fromfile(path, dtype=np.float32).reshape(-1, 2)


def _dialogue_anchor(baseline: list[dict]) -> tuple[dict, dict]:
    dialogue_layers = [
        x for x in baseline if x.get("role") == "dialogue" and not x.get("mute")
    ]
    controlled = [x for x in dialogue_layers if resolve_control(x.get("breathControl"))]
    if len(dialogue_layers) != 1 or len(controlled) != 1:
        raise BreathControlError(
            "frozen breath mix currently requires one dialogue anchor"
        )
    anchor = controlled[0]
    control = anchor.pop("breathControl")
    validate_document(control, "avo.breath-control.schema.json")
    if control.get("sourceSha256") != anchor["source"]["sha256"]:
        raise BreathControlError("breath source fingerprint is missing or stale")
    return anchor, control


def _baseline_and_control(layers: list[dict]) -> tuple[list[dict], dict, dict]:
    baseline = deepcopy(layers)
    anchor, control = _dialogue_anchor(baseline)
    for layer in baseline:
        resolve_control(layer.get("breathControl"), role=layer.get("role", ""))
        source = layer.get("source") or {}
        if not layer.get("mute"):
            actual = file_fingerprint(Path(source["locator"]))
            if actual["sha256"] != source.get("sha256"):
                raise BreathControlError("canonical source fingerprint mismatch")
        layer.pop("breathControl", None)
    return baseline, anchor, control


def materialize_breath_mix(layers: list[dict], directory: Path) -> dict:
    """Immutable, fingerprinted canonical intermediate; no export ancestry."""
    baseline, anchor, control = _baseline_and_control(layers)
    directory.mkdir(parents=True, exist_ok=False)
    frozen = _render_pcm(baseline, directory / "baseline.f32le")
    dialogue = _render_pcm([anchor], directory / "dialogue.f32le")
    output, delta = correct_frozen_mix(frozen, dialogue, control)
    path = directory / "mix.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-f",
            "f32le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-c:a",
            "pcm_f32le",
            str(path),
        ],
        input=output.astype(np.float32).tobytes(),
        capture_output=True,
        check=True,
    )
    active = np.any(delta != 0, axis=1)
    unchanged = np.array_equal(output[~active], frozen[~active])
    if not unchanged:
        raise BreathControlError("frozen mix changed outside breath windows")
    body = {
        "schemaVersion": "1.0.0",
        "generator": "frozen-dialogue-delta-v1",
        "layersSha256": content_hash(layers),
        "layers": layers,
        "sampleRate": 48000,
        "durationSamples": len(output),
        "controlSha256": content_hash(control),
        "normalization": "none",
        "outsideEventsBitIdentical": unchanged,
        "musicAndSfx": "frozen before breath treatment",
        "outputs": {
            name: file_fingerprint(directory / name)
            for name in ("baseline.f32le", "dialogue.f32le", "mix.wav")
        },
    }
    with (directory / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return {"path": path, "manifest": directory / "manifest.json", "qc": body}


def prepare_breath_layers(
    layers: list[dict], edit_dir: Path, resolve_path
) -> list[dict]:
    """Keep disabled render behavior unchanged; materialize enabled controls."""
    if not any(
        resolve_control(x.get("breathControl"), role=x.get("role", "")) for x in layers
    ):
        return layers
    frozen_layers = deepcopy(layers)
    for layer in frozen_layers:
        if (layer.get("source") or {}).get("locator"):
            layer["source"]["locator"] = str(
                resolve_path(layer["source"]["locator"], edit_dir)
            )
    result = materialize_breath_mix(
        frozen_layers, edit_dir / "audio" / f"breath-mix-{uuid4().hex}"
    )
    return [
        {
            "layerId": "breath-frozen",
            "role": "dialogue",
            "source": {"locator": str(result["path"])},
        }
    ]
