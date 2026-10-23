"""PCM Shorts mix: treated dialogue plus untouched timed effects, then two-pass loudness."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from avo.shorts_media import (
    CommandRunner,
    PreparedAsset,
    _default_runner,
    probe_media,
    sha256_file,
)
from avo.shorts_rules import SFX_ASSET_KEY, SFX_VOLUME, MediaPreparationError


def _mix_graph(
    prepared: Mapping[str, PreparedAsset],
    hits: Sequence[Mapping[str, Any]],
    duration: float,
) -> tuple[list[str], list[str]]:
    dialogue = prepared["dialogueAudio"]
    assets = [dialogue]
    samples = round(duration * 48000)
    filters = [
        (
            f"[0:a:0]aresample=48000,apad=whole_len={samples},atrim=end_sample={samples},"
            "asetpts=N/SR/TB[voice]"
        )
    ]
    labels = ["[voice]"]
    for index, hit in enumerate(hits, 1):
        start = float(hit["startSec"])
        if not math.isfinite(start) or not 0 <= start < duration:
            raise MediaPreparationError("SFX start lies outside edited duration")
        kind = str(hit["kind"])
        asset = prepared[SFX_ASSET_KEY[kind]]
        assets.append(asset)
        play = min(asset.duration_sec, duration - start)
        delay_samples = round(start * 48000)
        filters.append(
            f"[{index}:a:0]aresample=48000,atrim=duration={play},"
            f"asetpts=PTS-STARTPTS,volume={SFX_VOLUME[kind]},"
            f"adelay={delay_samples}S:all=1[sfx{index}]"
        )
        labels.append(f"[sfx{index}]")
    filters.append(
        "".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[mix]"
    )
    argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for asset in assets:
        if asset.muted or sha256_file(asset.path) != asset.sha256:
            raise MediaPreparationError(f"audio source changed or muted: {asset.path}")
        argv += ["-i", str(asset.path)]
    return argv, filters


def _checked(argv: Sequence[str], runner: CommandRunner):
    result = runner(argv)
    if result.returncode:
        raise MediaPreparationError(f"Shorts audio mix failed: {result.stderr[-4000:]}")
    return result


def mix_short_audio(
    prepared: Mapping[str, PreparedAsset | Mapping[str, Any]],
    item: Mapping[str, Any],
    output: Path,
    *,
    channels: int = 1,
    target_lufs: float = -16,
    true_peak: float = -1,
    runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    """Mix already treated original dialogue; NR is never applied to effects.

    The dialogue asset must include any approved ducked bed before this function.
    Both passes use the identical sample-timed graph. Non-finite measurement fails.
    """
    prepared = _prepared_assets(prepared, item.get("sfxHits") or [])
    duration = float(prepared["dialogueAudio"].duration_sec)
    _validate_mix_target(duration, channels, target_lufs, true_peak, output)
    source_clock = _dialogue_clock(prepared["dialogueAudio"], duration, runner)
    inputs, filters = _mix_graph(prepared, item.get("sfxHits") or [], duration)
    if output.resolve() in {asset.path.resolve() for asset in prepared.values()}:
        raise MediaPreparationError("audio mix output aliases an input")
    norm = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
    measure_graph = ";".join([*filters, f"[mix]{norm}:print_format=json[measured]"])
    measured = _checked(
        [
            *inputs,
            "-filter_complex",
            measure_graph,
            "-map",
            "[measured]",
            "-f",
            "null",
            "-",
        ],
        runner,
    )
    values = _measurement(measured.stderr)
    norm += (
        f":measured_I={values['input_i']}:measured_TP={values['input_tp']}"
        f":measured_LRA={values['input_lra']}:measured_thresh={values['input_thresh']}"
        f":offset={values['target_offset']}:linear=true"
    )
    # Dynamic loudnorm timestamps include its lookahead (90 ms on FFmpeg 7).
    # Reset to the emitted sample clock before output -t, which otherwise cuts
    # real tail samples even though loudnorm emitted the full signal.
    graph = ";".join([*filters, f"[mix]{norm},aresample=48000,asetpts=N/SR/TB[outa]"])
    output.parent.mkdir(parents=True, exist_ok=True)
    _checked(
        [
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[outa]",
            "-vn",
            "-t",
            str(duration),
            "-ar",
            "48000",
            "-ac",
            str(channels),
            "-c:a",
            "pcm_s24le",
            str(output),
        ],
        runner,
    )
    _validate_mix_output(output, duration, runner)
    return {
        "path": str(output.resolve()),
        "sha256": sha256_file(output),
        "durationSec": duration,
        "measurements": values,
        "targetLufs": target_lufs,
        "truePeakDbtp": true_peak,
        "sourceClock": source_clock,
    }


def _prepared_assets(prepared, hits):
    keys = {"dialogueAudio", *(SFX_ASSET_KEY[str(hit["kind"])] for hit in hits)}
    result = {}
    for key in keys:
        asset = prepared[key]
        if isinstance(asset, Mapping):
            asset = PreparedAsset(
                Path(asset["path"]),
                str(asset["hash"]),
                float(asset["durationSec"]),
                bool(asset.get("muted", False)),
            )
        result[key] = asset
    return result


def _measurement(stderr):
    try:
        measurement = json.loads(re.findall(r"\{[^{}]+\}", stderr)[-1])
        values = {
            key: float(measurement[key])
            for key in (
                "input_i",
                "input_tp",
                "input_lra",
                "input_thresh",
                "target_offset",
            )
        }
    except (IndexError, KeyError, ValueError) as exc:
        raise MediaPreparationError("missing loudness measurement") from exc
    if not all(math.isfinite(value) for value in values.values()):
        raise MediaPreparationError("non-finite loudness measurement")
    return values


def _validate_mix_target(duration, channels, target_lufs, true_peak, output):
    if not math.isfinite(duration) or duration <= 0 or channels not in {1, 2}:
        raise MediaPreparationError("audio duration/channels invalid")
    if not (math.isfinite(target_lufs) and math.isfinite(true_peak)):
        raise MediaPreparationError("loudness targets must be finite")
    if output.suffix.lower() != ".wav":
        raise MediaPreparationError("source-fidelity mix requires a PCM WAV output")


def _validate_mix_output(output, duration, runner):
    probe = probe_media(output, runner)
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    if audio["codec_name"] != "pcm_s24le" or audio["sample_rate"] != "48000":
        raise MediaPreparationError("mixed audio lost its PCM 48 kHz contract")
    if abs(float(probe["format"]["duration"]) - duration) > 1 / 48000 + 0.000001:
        raise MediaPreparationError("mixed audio duration changed")


def _dialogue_clock(asset, duration, runner):
    probe = probe_media(asset.path, runner)
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    if str(audio["sample_rate"]) != "48000":
        raise MediaPreparationError(
            "prepared dialogue must use the canonical 48 kHz clock"
        )
    actual = round(float(audio["duration"]) * 48000)
    expected = round(duration * 48000)
    difference = expected - actual
    # The prepared stem can end within one CFR frame of its canonical boundary.
    # Account only for that declared trailing gap; never replace missing content.
    if not 0 <= difference <= 1602:
        raise MediaPreparationError(
            "prepared dialogue sample count differs from canonical duration"
        )
    return {
        "inputSamples": actual,
        "canonicalSamples": expected,
        "trailingPaddingSamples": difference,
        "sampleRate": 48000,
    }
