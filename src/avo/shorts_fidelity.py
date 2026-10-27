"""Compose original Shorts picture in 10 bits; HTML supplies graphics alpha only."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from avo.shorts_media import (
    CommandRunner,
    _default_runner,
    probe_media,
    sha256_file,
)
from avo.shorts_rules import MediaPreparationError

PROHIBITED = {"proof", "preview", "proxy", "master", "delivery"}


def registered_implementation():
    """Resolve this specialized built-in without widening the sequential executor."""
    from avo.capabilities import CapabilityRegistry
    from avo.shorts_contract import content_hash

    root = Path(__file__).parent
    paths = [
        root / name
        for name in (
            "shorts_fidelity.py",
            "shorts_fidelity_audio.py",
            "shorts_media.py",
            "shorts_visuals.py",
        )
    ]
    paths += sorted((root / "templates" / "shorts_hyperframes").glob("*.*"))
    registry = CapabilityRegistry()
    record = registry.register_record(
        {
            "implementationId": "impl-shorts-source-fidelity",
            "capability": "shorts-source-fidelity",
            "kind": "built-in",
            "adapterId": "ffmpeg.shorts-source-fidelity",
            "version": "1.0.0",
            "sha256": content_hash(
                {str(path.relative_to(root)): sha256_file(path) for path in paths}
            ),
        }
    )
    return registry.resolve(record.capability).proof_reference()


def _number(value: Any) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise MediaPreparationError("non-finite render parameter")
    return value


def _asset(
    path: Path, fingerprint: str, lock: Mapping[str, str], ancestry: Sequence
) -> None:
    for item in ancestry:
        if item.get("mediaClass") in PROHIBITED:
            raise MediaPreparationError(f"forbidden picture ancestry: {path}: {item}")
        _asset_ancestry(path, item.get("ancestry") or [])
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise MediaPreparationError(f"missing SHA-256 dependency: {path}")
    if fingerprint not in lock.values() or sha256_file(path) != fingerprint:
        raise MediaPreparationError(
            f"source fingerprint/dependency lock mismatch: {path}"
        )


def _asset_ancestry(path: Path, ancestry: Sequence) -> None:
    for item in ancestry:
        if item.get("mediaClass") in PROHIBITED:
            raise MediaPreparationError(f"forbidden picture ancestry: {path}: {item}")
        _asset_ancestry(path, item.get("ancestry") or [])


def _original_path(path: Path) -> None:
    if re.search(
        r"(?:^|[/\\])(?:proofs?|previews?|masters?|delivery|renders)(?:[/\\]|$)",
        str(path),
        re.IGNORECASE,
    ) or re.search(
        r"(?:^|[-_])(?:proof|preview|master)(?:[-_.]|$)", path.name, re.IGNORECASE
    ):
        raise MediaPreparationError(f"forbidden original/insert picture path: {path}")


def _rect(
    rect: Mapping[str, Any], width: int, height: int
) -> tuple[int, int, int, int]:
    x, y, w, h = (_number(rect[key]) for key in ("x", "y", "width", "height"))
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise MediaPreparationError("visual rectangle must fit normalized canvas")
    return tuple(
        round(value * extent / 2) * 2
        for value, extent in ((x, width), (y, height), (w, width), (h, height))
    )


def _scale(width: int, height: int, fit: str) -> str:
    if width < 2 or height < 2:
        raise MediaPreparationError("visual rectangle is smaller than two pixels")
    if fit == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x10152b"
        )
    if fit != "cover":
        raise MediaPreparationError("fit must be contain or cover")
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


def build_fidelity_command(
    source: Path,
    output: Path,
    *,
    source_segments: Sequence[Mapping[str, Any]],
    source_sha256: str,
    canonical_lock: Mapping[str, str],
    width: int = 1728,
    height: int = 3072,
    fps: str = "30000/1001",
    speed: float = 1.0,
    visual_inserts: Sequence[Mapping[str, Any]] = (),
    punch_ins: Sequence[Mapping[str, Any]] = (),
    source_ancestry: Sequence = (),
    overlay_path: Path | None = None,
    overlay_sha256: str | None = None,
    mixed_audio_path: Path | None = None,
    mixed_audio_sha256: str | None = None,
    crf: int = 14,
    preset: str = "slow",
    window: Mapping[str, float] | None = None,
    runner: CommandRunner = _default_runner,
) -> list[str]:
    """Build a locked original-to-HEVC command, never using a prepared video base.

    ``canonical_lock`` contains the canonical timeline dependency hashes AND every
    media SHA-256, including the generated graphics-only alpha and mixed audio.
    Those generated assets must be reconstructed from the same canonical lock by
    the caller. Video inserts are silent and finite. Coordinates are normalized.
    """
    source, output = Path(source).resolve(), Path(output).resolve()
    _original_path(source)
    _asset(source, source_sha256, canonical_lock, source_ancestry)
    speed = _validate_source(source, width, height, fps, speed, source_segments, runner)
    argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-filter_complex_threads", "1"]
    filters: list[str] = []
    duration = 0.0
    paths = [source]
    for index, segment in enumerate(source_segments):
        start, end = _number(segment["startSec"]), _number(segment["endSec"])
        if start < 0 or end <= start:
            raise MediaPreparationError("invalid source segment")
        if segment.get("sourceFingerprint", source_sha256) != source_sha256:
            raise MediaPreparationError("segment fingerprint differs from original")
        argv += ["-ss", f"{start:.6f}", "-t", f"{end - start:.6f}", "-i", str(source)]
        filters.append(
            f"[{index}:v:0]setpts=(PTS-STARTPTS)/{speed:.8g},fps={fps},"
            f"{_scale(width, height, 'cover')},setsar=1,format=yuv420p10le[s{index}]"
        )
        duration += (end - start) / speed
    filters.append(
        "".join(f"[s{i}]" for i in range(len(source_segments)))
        + f"concat=n={len(source_segments)}:v=1:a=0[base]"
    )
    current = "base"
    current = _add_punches(filters, current, punch_ins, duration, width, height)
    current, next_input = _add_inserts(
        argv,
        filters,
        paths,
        current,
        len(source_segments),
        visual_inserts,
        canonical_lock,
        duration,
        width,
        height,
        fps,
    )
    current, next_input = _add_overlay(
        argv,
        filters,
        paths,
        current,
        next_input,
        overlay_path,
        overlay_sha256,
        canonical_lock,
        width,
        height,
        runner,
    )
    audio_map = None
    if mixed_audio_path:
        mixed_audio_path = Path(mixed_audio_path).resolve()
        _asset(mixed_audio_path, mixed_audio_sha256 or "", canonical_lock, [])
        argv += ["-i", str(mixed_audio_path)]
        paths.append(mixed_audio_path)
        audio_map = f"{next_input}:a:0"
    if output in paths:
        raise MediaPreparationError(f"output aliases an input: {output}")
    filters.append(
        f"[{current}]setparams=range=limited:color_primaries=bt709:"
        "color_trc=bt709:colorspace=bt709[final]"
    )
    argv += ["-filter_complex", ";".join(filters), "-map", "[final]"]
    argv += (
        ["-map", audio_map, "-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
        if audio_map
        else ["-an"]
    )
    export_duration = _export_window(argv, window, duration)
    argv += [
        "-t",
        f"{export_duration:.6f}",
        "-r",
        str(fps),
        "-c:v",
        "libx265",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p10le",
        "-tag:v",
        "hvc1",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-x265-params",
        "log-level=error:colorprim=bt709:transfer=bt709:colormatrix=bt709",
        "-movflags",
        "+faststart",
        str(output),
    ]
    return argv


def _window(event: Mapping[str, Any], duration: float) -> tuple[float, float]:
    start, end = _number(event["startSec"]), _number(event["endSec"])
    if start < 0 or end <= start or end > duration + 0.000001:
        raise MediaPreparationError("visual event lies outside edited duration")
    return start, end


def render_fidelity(
    source: Path,
    output: Path,
    *,
    runner: CommandRunner = _default_runner,
    **kwargs: Any,
) -> dict[str, Any]:
    """Render and refuse success if the encoded picture lost the 10-bit contract."""
    command = build_fidelity_command(source, output, runner=runner, **kwargs)
    result = runner(command)
    if result.returncode:
        raise MediaPreparationError(
            f"source-fidelity render failed: {result.stderr[-4000:]}"
        )
    probe = probe_media(output, runner)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    expected = {
        "codec_name": "hevc",
        "pix_fmt": "yuv420p10le",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "width": kwargs.get("width", 1728),
        "height": kwargs.get("height", 3072),
    }
    for key, value in expected.items():
        if video.get(key) != value:
            raise MediaPreparationError(
                f"source-fidelity output violates {key}: {video.get(key)}"
            )
    _validate_output_rates(probe, video, kwargs)
    return {
        "path": str(Path(output).resolve()),
        "sha256": sha256_file(Path(output)),
        "canonicalInputLock": dict(kwargs["canonical_lock"]),
        "video": video,
    }


def _validate_source(source, width, height, fps, speed, source_segments, runner):
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise MediaPreparationError(
            "10-bit 4:2:0 canvas requires positive even dimensions"
        )
    if not re.fullmatch(r"[1-9][0-9]*(?:/[1-9][0-9]*)?", str(fps)):
        raise MediaPreparationError("fps must be a positive integer or rational")
    speed = _number(speed)
    if speed <= 0 or not source_segments:
        raise MediaPreparationError("positive speed and source segments required")
    _validate_source_color(source, runner)
    return speed


def _add_overlay(
    argv,
    filters,
    paths,
    current,
    next_input,
    overlay_path,
    overlay_sha256,
    canonical_lock,
    width,
    height,
    runner,
):
    if overlay_path:
        overlay_path = Path(overlay_path).resolve()
        _asset(overlay_path, overlay_sha256 or "", canonical_lock, [])
        overlay_probe = probe_media(overlay_path, runner)
        overlay_stream = next(
            s for s in overlay_probe["streams"] if s["codec_type"] == "video"
        )
        overlay_tags = {
            str(key).lower(): value
            for key, value in (overlay_stream.get("tags") or {}).items()
        }
        if (
            not overlay_stream.get("pix_fmt", "").startswith(
                ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya")
            )
            and str(overlay_tags.get("alpha_mode", "0")) != "1"
        ):
            raise MediaPreparationError(
                "graphics overlay must contain an alpha channel"
            )
        if overlay_stream.get("codec_name") == "vp9":
            argv += ["-c:v", "libvpx-vp9"]
        argv += ["-i", str(overlay_path)]
        paths.append(overlay_path)
        filters += [
            (
                f"[{next_input}:v:0]setpts=PTS-STARTPTS,scale={width}:{height},"
                "format=yuva420p10le[graphics]"
            ),
            f"[{current}][graphics]overlay=format=yuv420p10:eof_action=pass[captioned]",
        ]
        current = "captioned"
        next_input += 1
    return current, next_input


def _add_inserts(
    argv,
    filters,
    paths,
    current,
    next_input,
    visual_inserts,
    canonical_lock,
    duration,
    width,
    height,
    fps,
):
    region_windows: list[tuple[float, float]] = []
    for index, insert in enumerate(visual_inserts):
        path = Path(insert["path"]).resolve()
        _original_path(path)
        _asset(
            path,
            str(insert["sha256"]),
            canonical_lock,
            [
                {
                    "mediaClass": insert.get("mediaClass", "source"),
                    "ancestry": insert.get("ancestry", []),
                }
            ],
        )
        paths.append(path)
        start, end = _window(insert, duration)
        enable = f"gte(t,{start})*lt(t,{end})"
        if insert.get("baseRegion"):
            if any(start < b and end > a for a, b in region_windows):
                raise MediaPreparationError("baseRegion windows must not overlap")
            region_windows.append((start, end))
            x, y, w, h = _rect(insert["baseRegion"], width, height)
            filters += [
                f"[{current}]split=2[bg{index}][record{index}]",
                f"[bg{index}]drawbox=color=0x10152b:t=fill:enable='{enable}'[blank{index}]",
                f"[record{index}]{_scale(w, h, 'cover')},format=yuv420p10le[region{index}]",
                (
                    f"[blank{index}][region{index}]overlay=x={x}:y={y}:format=yuv420p10:"
                    f"enable='{enable}'[layout{index}]"
                ),
            ]
            current = f"layout{index}"
        if insert["kind"] == "image":
            argv += [
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-t",
                str(end - start),
                "-i",
                str(path),
            ]
            stream = "v:0"
        elif insert["kind"] == "video":
            first, last = (
                _number(insert["sourceStartSec"]),
                _number(insert["sourceEndSec"]),
            )
            if first < 0 or abs(last - first - (end - start)) > 0.001:
                raise MediaPreparationError(
                    "video insertion must match finite source window"
                )
            argv += ["-ss", str(first), "-t", str(last - first), "-i", str(path)]
            stream = str(int(insert["videoStreamIndex"]))
        else:
            raise MediaPreparationError("visual insert kind must be image or video")
        x, y, w, h = _rect(insert["rect"], width, height)
        filters += [
            (
                f"[{next_input}:{stream}]setpts=PTS-STARTPTS,fps={fps},"
                f"{_scale(w, h, insert.get('fit', 'contain'))},format=yuv420p10le,"
                f"setpts=PTS+{start}/TB[insert{index}]"
            ),
            (
                f"[{current}][insert{index}]overlay=x={x}:y={y}:format=yuv420p10:"
                f"eof_action=pass:enable='{enable}'[visual{index}]"
            ),
        ]
        current = f"visual{index}"
        next_input += 1
    return current, next_input


def _add_punches(filters, current, punch_ins, duration, width, height):
    for index, punch in enumerate(punch_ins):
        start, end = _window(punch, duration)
        scale = _number(punch["scale"])
        if scale < 1 or scale > 3:
            raise MediaPreparationError("punch scale must be between 1 and 3")
        factor = f"if(gte(t,{start})*lt(t,{end}),{scale},1)"
        label = f"punch{index}"
        filters.append(
            f"[{current}]scale=w='trunc({width}*{factor}/2)*2':"
            f"h='trunc({height}*{factor}/2)*2':eval=frame,"
            f"crop={width}:{height},format=yuv420p10le[{label}]"
        )
        current = label
    return current


def _validate_source_color(source, runner):
    source_probe = probe_media(source, runner)
    video = next(
        (s for s in source_probe.get("streams", []) if s["codec_type"] == "video"), {}
    )
    if video.get("pix_fmt") != "yuv420p10le":
        raise MediaPreparationError(
            "source-fidelity path requires original yuv420p10le picture"
        )
    if any(
        video.get(key) not in (None, "unknown", "bt709")
        for key in ("color_space", "color_transfer", "color_primaries")
    ):
        raise MediaPreparationError("source-fidelity path supports BT.709 SDR only")


def _validate_output_rates(probe, video, kwargs):
    expected_fps = Fraction(str(kwargs.get("fps", "30000/1001")))
    if Fraction(video.get("r_frame_rate", "0/1")) != expected_fps:
        raise MediaPreparationError("source-fidelity output frame rate changed")
    _validate_output_duration(probe, kwargs, expected_fps)
    if kwargs.get("mixed_audio_path"):
        audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
        if str(audio.get("sample_rate")) != "48000":
            raise MediaPreparationError("source-fidelity audio must remain at 48 kHz")


def _validate_output_duration(probe, kwargs, fps):
    duration = sum(
        float(row["endSec"]) - float(row["startSec"])
        for row in kwargs["source_segments"]
    ) / float(kwargs.get("speed", 1))
    if kwargs.get("window"):
        duration = kwargs["window"]["endSec"] - kwargs["window"]["startSec"]
    if abs(float(probe["format"]["duration"]) - duration) > 1 / float(fps) + 0.001:
        raise MediaPreparationError("source-fidelity output duration changed")


def _export_window(argv, window, duration):
    export_duration = duration
    if window:
        first, last = _window(window, duration)
        argv += ["-ss", f"{first:.6f}"]
        export_duration = last - first
    return export_duration


def _microproof_windows(item, duration):
    events = [{"kind": "opening", "startSec": 0, "endSec": min(0.75, duration)}]
    for kind in ("image", "video"):
        matches = sorted(
            (row for row in item.get("visualInserts", []) if row["kind"] == kind),
            key=lambda row: row["startSec"],
        )
        if matches:
            events.append({**matches[0], "kind": kind})
    punches = sorted(item.get("punchIns", []), key=lambda row: row["startSec"])
    if punches:
        events.append({**punches[0], "kind": "punch"})
    return _deduplicate_microproof_windows(events, duration)


def _deduplicate_microproof_windows(events, duration):
    windows = {}
    for event in events:
        first, last = _window(event, duration)
        length = min(0.75, last - first)
        start = round((first + last - length) / 2, 6)
        end = round(start + length, 6)
        key = (start, end)
        row = windows.setdefault(
            key, {"window": {"startSec": start, "endSec": end}, "cases": []}
        )
        row["cases"].append(event["kind"])
    return list(windows.values())


def build_microproofs(
    source: Path,
    output_dir: Path,
    *,
    plan_hash: str,
    item: Mapping[str, Any],
    source_sha256: str,
    width: int,
    height: int,
    fps: str,
    mixed_audio_path: Path | None = None,
    mixed_audio_sha256: str | None = None,
    runner: CommandRunner = _default_runner,
    graphics_review: str = "separate native HyperFrames check and snapshots required",
) -> dict[str, Any]:
    """Gate the same original picture/audio graph before expensive HTML alpha.

    This does not examine captions/graphics. The caller must separately gate the
    selected graphics renderer and complete its separate visual review.
    """
    from avo.shorts_contract import atomic_write_json, content_hash

    if not re.fullmatch(r"[a-f0-9]{64}", plan_hash):
        raise MediaPreparationError("microproof gate requires immutable plan SHA-256")
    implementation = registered_implementation()
    lock = {
        "plan": plan_hash,
        "item": content_hash(item),
        "source": source_sha256,
        "implementation": implementation["sha256"],
    }
    lock.update(
        {f"insert:{row['id']}": row["sha256"] for row in item.get("visualInserts", [])}
    )
    if mixed_audio_path:
        lock["mixed-audio"] = mixed_audio_sha256 or ""
    segments = item["sourceSegments"]
    speed = float(item.get("speed", 1))
    duration = (
        sum(float(row["endSec"]) - float(row["startSec"]) for row in segments) / speed
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, window in enumerate(_microproof_windows(item, duration), 1):
        result = render_fidelity(
            source,
            output_dir / f"micro-{index:02d}.mp4",
            source_segments=segments,
            source_sha256=source_sha256,
            canonical_lock=lock,
            width=width,
            height=height,
            fps=fps,
            speed=speed,
            visual_inserts=item.get("visualInserts", []),
            punch_ins=item.get("punchIns", []),
            mixed_audio_path=mixed_audio_path,
            mixed_audio_sha256=mixed_audio_sha256,
            window=window["window"],
            preset="ultrafast",
            runner=runner,
        )
        results.append({**window, "status": "passed", **result})
    if registered_implementation()["sha256"] != implementation["sha256"]:
        raise MediaPreparationError("microproof implementation changed during render")
    gate = {
        "planHash": plan_hash,
        "itemId": item["id"],
        "status": "passed",
        "scope": "original-picture-and-mixed-audio-only",
        "graphicsReview": graphics_review,
        "implementationRef": implementation,
        "canonicalInputLock": lock,
        "results": results,
    }
    path = output_dir / "microproof-gate.json"
    atomic_write_json(path, gate)
    return {**gate, "path": str(path.resolve()), "sha256": sha256_file(path)}
