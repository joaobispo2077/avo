"""Deterministic media preparation for parameter-driven Shorts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class MediaPreparationError(RuntimeError):
    """A source cannot be prepared without violating the resolved plan."""


@dataclass(frozen=True)
class PreparedAsset:
    path: Path
    sha256: str
    duration_sec: float
    muted: bool = False

    def as_contract(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "hash": self.sha256,
            "durationSec": round(self.duration_sec, 6),
            "muted": self.muted,
        }


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), text=True, capture_output=True, check=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


SFX_VOLUME = {
    "chip": 0.30,
    "stamp": 0.34,
    "punch": 0.22,
    "seam": 0.20,
    "price": 0.28,
}
SFX_ASSET_KEY = {
    "chip": "sfxChip",
    "stamp": "sfxStamp",
    "punch": "sfxPunch",
    "seam": "sfxSeam",
    "price": "sfxPrice",
}
SFX_FILE_NAME = {key: f"sfx-{kind}.m4a" for kind, key in SFX_ASSET_KEY.items()}


def atempo_chain(speed: float) -> str:
    """Return a pitch-preserving tempo chain within FFmpeg's per-filter range."""
    if speed <= 0:
        raise MediaPreparationError("speed must be positive")
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.8g}" for factor in factors)


def base_video_command(
    source: Path,
    output: Path,
    *,
    start_sec: float,
    end_sec: float,
    speed: float,
    fps: float,
    width: int,
    height: int,
    crop_mode: str = "cover",
) -> list[str]:
    duration = (end_sec - start_sec) / speed
    if duration <= 0:
        raise MediaPreparationError("source range must have positive duration")
    if crop_mode == "contain":
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        )
    else:
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    vf = f"setpts=(PTS-STARTPTS)/{speed:.8g},fps={fps:.8g},{scale},format=yuv420p"
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-ss",
        f"{start_sec:.6f}",
        "-to",
        f"{end_sec:.6f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        vf,
        "-t",
        f"{duration:.6f}",
        "-r",
        f"{fps:.8g}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-force_key_frames",
        "expr:gte(t,n_forced*1)",
        str(output),
    ]


def dialogue_audio_command(
    source: Path,
    output: Path,
    *,
    start_sec: float,
    end_sec: float,
    speed: float,
    sample_rate: int = 48000,
    channels: int = 2,
) -> list[str]:
    duration = (end_sec - start_sec) / speed
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-ss",
        f"{start_sec:.6f}",
        "-to",
        f"{end_sec:.6f}",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        f"asetpts=PTS-STARTPTS,{atempo_chain(speed)}",
        "-t",
        f"{duration:.6f}",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output),
    ]


def _run(command: Sequence[str], runner: CommandRunner) -> None:
    result = runner(command)
    if result.returncode:
        raise MediaPreparationError(
            f"media command failed ({result.returncode}): {result.stderr.strip()}"
        )


def prepare_base_assets(
    source: Path,
    output_dir: Path,
    *,
    start_sec: float,
    end_sec: float,
    speed: float,
    fps: float = 30,
    width: int = 1080,
    height: int = 1920,
    sample_rate: int = 48000,
    channels: int = 2,
    crop_mode: str = "cover",
    runner: CommandRunner = _default_runner,
) -> dict[str, PreparedAsset]:
    """Prepare exact-duration muted video and separate pitch-preserved dialogue."""
    source = source.resolve()
    if not source.is_file():
        raise MediaPreparationError(f"source does not exist: {source}")
    output_dir.mkdir(parents=True, exist_ok=True)
    video = output_dir / "base-video.mp4"
    audio = output_dir / "dialogue-audio.m4a"
    _run(
        base_video_command(
            source,
            video,
            start_sec=start_sec,
            end_sec=end_sec,
            speed=speed,
            fps=fps,
            width=width,
            height=height,
            crop_mode=crop_mode,
        ),
        runner,
    )
    _run(
        dialogue_audio_command(
            source,
            audio,
            start_sec=start_sec,
            end_sec=end_sec,
            speed=speed,
            sample_rate=sample_rate,
            channels=channels,
        ),
        runner,
    )
    if not video.is_file() or not audio.is_file():
        raise MediaPreparationError("media runner did not create both expected assets")
    duration = (end_sec - start_sec) / speed
    return {
        "baseVideo": PreparedAsset(video, sha256_file(video), duration, True),
        "dialogueAudio": PreparedAsset(audio, sha256_file(audio), duration, False),
    }


def prepare_ordered_base_assets(
    source: Path,
    output_dir: Path,
    *,
    source_segments: Sequence[Mapping[str, Any]],
    speed: float,
    fps: float = 30,
    width: int = 1080,
    height: int = 1920,
    sample_rate: int = 48000,
    channels: int = 2,
    crop_mode: str = "cover",
    seam_safety_sec: float = 0.03,
    runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    """Prepare declared-order picture/dialogue with no chronological re-sort."""
    if not source_segments:
        raise MediaPreparationError("ordered source segments cannot be empty")
    source = source.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = _prepare_ordered_segments(
        source,
        output_dir,
        source_segments,
        speed=speed,
        fps=fps,
        width=width,
        height=height,
        sample_rate=sample_rate,
        channels=channels,
        crop_mode=crop_mode,
        runner=runner,
    )
    video = output_dir / "base-video.mp4"
    audio = output_dir / "dialogue-audio.m4a"
    video_inputs = [part["baseVideo"].path for part in prepared]
    audio_inputs = [part["dialogueAudio"].path for part in prepared]
    _run(_concat_video_command(video_inputs, video), runner)
    _run(
        _concat_audio_command(
            audio_inputs,
            prepared,
            audio,
            sample_rate=sample_rate,
            channels=channels,
            seam_safety_sec=seam_safety_sec,
        ),
        runner,
    )
    if not video.is_file() or not audio.is_file():
        raise MediaPreparationError(
            "ordered concat did not create both expected assets"
        )
    total = sum(part["baseVideo"].duration_sec for part in prepared)
    windows = _join_windows(source_segments, prepared, total, seam_safety_sec)
    return {
        "baseVideo": PreparedAsset(video, sha256_file(video), total, True),
        "dialogueAudio": PreparedAsset(audio, sha256_file(audio), total, False),
        "joinWindows": windows,
    }


def _prepare_ordered_segments(
    source: Path,
    output_dir: Path,
    segments: Sequence[Mapping[str, Any]],
    **options: Any,
) -> list[dict[str, PreparedAsset]]:
    prepared = []
    for position, segment in enumerate(segments, 1):
        if int(segment.get("order") or 0) != position:
            raise MediaPreparationError(
                "source segment order must equal array position; no auto-sort is allowed"
            )
        prepared.append(
            prepare_base_assets(
                source,
                output_dir / f"segment-{position:03d}",
                start_sec=float(segment["startSec"]),
                end_sec=float(segment["endSec"]),
                **options,
            )
        )
    return prepared


def _concat_video_command(inputs: list[Path], output: Path) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for path in inputs:
        command.extend(["-i", str(path)])
    labels = "".join(f"[{index}:v:0]" for index in range(len(inputs)))
    command.extend(
        [
            "-filter_complex",
            f"{labels}concat=n={len(inputs)}:v=1:a=0[v]",
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
    )
    return command


def _concat_audio_command(
    inputs: list[Path],
    prepared: list[dict[str, PreparedAsset]],
    output: Path,
    *,
    sample_rate: int,
    channels: int,
    seam_safety_sec: float,
) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for path in inputs:
        command.extend(["-i", str(path)])
    filters = []
    for index, part in enumerate(prepared):
        duration = part["dialogueAudio"].duration_sec
        fade_out = max(0.0, duration - seam_safety_sec)
        filters.append(
            f"[{index}:a:0]afade=t=in:st=0:d={seam_safety_sec:.3f},"
            f"afade=t=out:st={fade_out:.6f}:d={seam_safety_sec:.3f}[a{index}]"
        )
    labels = "".join(f"[a{index}]" for index in range(len(inputs)))
    command.extend(
        [
            "-filter_complex",
            ";".join(filters) + ";" + labels + f"concat=n={len(inputs)}:v=0:a=1[a]",
            "-map",
            "[a]",
            "-vn",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-c:a",
            "aac",
            str(output),
        ]
    )
    return command


def _join_windows(
    segments: Sequence[Mapping[str, Any]],
    prepared: list[dict[str, PreparedAsset]],
    total: float,
    seam_safety_sec: float,
) -> list[dict[str, Any]]:
    windows = []
    cursor = 0.0
    for left, right, part in zip(segments, segments[1:], prepared[:-1]):
        cursor += part["baseVideo"].duration_sec
        windows.append(
            {
                "start": round(max(0.0, cursor - seam_safety_sec / 2), 6),
                "end": round(min(total, cursor + seam_safety_sec / 2), 6),
                "reason": f"ordered segment seam {left.get('segmentId')} -> {right.get('segmentId')}",
            }
        )
    return windows


def probe_media(path: Path, runner: CommandRunner = _default_runner) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path.resolve()),
    ]
    result = runner(command)
    if result.returncode:
        raise MediaPreparationError(result.stderr.strip() or f"cannot probe {path}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaPreparationError(f"invalid ffprobe JSON for {path}") from exc


def _parse_filter_events(stderr: str, prefix: str) -> list[dict[str, str]]:
    events = []
    for line in stderr.splitlines():
        if prefix not in line:
            continue
        payload = line.split(f"{prefix}:", 1)[-1].strip()
        parsed: dict[str, str] = {}
        for token in payload.split():
            if "=" in token:
                key, value = token.split("=", 1)
                parsed[key] = value
        if parsed:
            events.append(parsed)
    return events


def measure_audio_loudness(
    path: Path, *, runner: CommandRunner = _default_runner
) -> dict[str, float | None]:
    """Return integrated LUFS and true-peak dBTP from ffmpeg ebur128."""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-v",
        "info",
        "-i",
        str(path.resolve()),
        "-af",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    result = runner(command)
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None
    for line in (result.stderr or "").splitlines():
        if "TARGET:" in line:
            continue
        if "I:" in line and "LUFS" in line:
            try:
                integrated_lufs = float(line.split("I:")[1].split("LUFS")[0].strip())
            except ValueError:
                continue
        if "Peak:" in line and "dBFS" in line:
            try:
                true_peak_dbtp = float(line.split("Peak:")[1].split("dBFS")[0].strip())
            except ValueError:
                continue
    return {"integratedLufs": integrated_lufs, "truePeakDbtp": true_peak_dbtp}


VOICE_QUIET_LUFS = -24.0
VOICE_HOT_LUFS = -8.0
VOICE_TARGET_LUFS = -16.0
VOICE_TP_CEILING_DBTP = -1.0
SFX_DIALOGUE_TP_CEILING_DBTP = -5.0
DUCK_RATIO = 8.0
DUCK_ATTACK_MS = 20.0
DUCK_RELEASE_MS = 250.0


def dialogue_gain_filter(
    integrated_lufs: float | None,
    true_peak_dbtp: float | None,
    *,
    tp_ceiling: float = VOICE_TP_CEILING_DBTP,
) -> str | None:
    """Gain only when dialogue is outside the QC band or true-peak is hot."""
    if integrated_lufs is None:
        return None
    in_band = VOICE_QUIET_LUFS <= integrated_lufs <= VOICE_HOT_LUFS
    peak_hot = true_peak_dbtp is not None and true_peak_dbtp > tp_ceiling
    if in_band and not peak_hot:
        return None
    gain_db = 0.0 if in_band else VOICE_TARGET_LUFS - integrated_lufs
    if true_peak_dbtp is not None:
        gain_db = min(gain_db, tp_ceiling - true_peak_dbtp)
    if abs(gain_db) < 0.05:
        return None
    return f"volume={gain_db:.3f}dB"


def ducked_mix_command(
    dialogue: Path,
    bed: Path,
    output: Path,
    *,
    gain_filter: str | None = None,
) -> list[str]:
    """Duck an already-leveled insert bed under dialogue into one 48 kHz stem."""
    dialogue_chain = (
        "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    )
    if gain_filter:
        dialogue_chain += f",{gain_filter}"
    dialogue_chain += ",asplit=2[dlg][sc]"
    filters = [
        dialogue_chain,
        "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[bedin]",
        (
            f"[bedin][sc]sidechaincompress=threshold=0.05:ratio={DUCK_RATIO:g}:"
            f"attack={DUCK_ATTACK_MS:g}:release={DUCK_RELEASE_MS:g}[bed]"
        ),
        "[dlg][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[outa]",
    ]
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(dialogue),
        "-i",
        str(bed),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outa]",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "aac",
        str(output),
    ]


def mix_ducked_bed_into_dialogue(
    dialogue: Path,
    bed: Path,
    output: Path,
    *,
    duration_sec: float,
    runner: CommandRunner = _default_runner,
) -> PreparedAsset:
    """Replace dialogue with a sidechain-ducked mix; do not also play the bed."""
    measured = measure_audio_loudness(dialogue, runner=runner)
    gain_filter = dialogue_gain_filter(
        measured.get("integratedLufs"), measured.get("truePeakDbtp")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ducked_mix_command(dialogue, bed, output, gain_filter=gain_filter),
        runner,
    )
    if not output.is_file():
        raise MediaPreparationError("ducked dialogue mix was not created")
    return PreparedAsset(output, sha256_file(output), duration_sec, False)


def apply_dialogue_gain_if_needed(
    dialogue: PreparedAsset,
    output: Path,
    *,
    tp_ceiling: float = VOICE_TP_CEILING_DBTP,
    runner: CommandRunner = _default_runner,
) -> PreparedAsset:
    """Raise or lower a quiet/hot dialogue stem; skip when already in band."""
    measured = measure_audio_loudness(dialogue.path, runner=runner)
    gain_filter = dialogue_gain_filter(
        measured.get("integratedLufs"),
        measured.get("truePeakDbtp"),
        tp_ceiling=tp_ceiling,
    )
    if not gain_filter:
        return dialogue
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(dialogue.path),
            "-af",
            gain_filter,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "aac",
            str(output),
        ],
        runner,
    )
    if not output.is_file():
        raise MediaPreparationError("gained dialogue stem was not created")
    gained = PreparedAsset(output, sha256_file(output), dialogue.duration_sec, False)
    after = measure_audio_loudness(gained.path, runner=runner)
    integrated = after.get("integratedLufs")
    if integrated is None or VOICE_QUIET_LUFS <= integrated <= VOICE_HOT_LUFS:
        return gained
    normalized = output.with_name("dialogue-loudnorm.m4a")
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(gained.path),
            "-af",
            f"loudnorm=I={VOICE_TARGET_LUFS:g}:TP={tp_ceiling:g}:LRA=11",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "aac",
            str(normalized),
        ],
        runner,
    )
    if not normalized.is_file():
        raise MediaPreparationError("loudnorm dialogue stem was not created")
    return PreparedAsset(
        normalized, sha256_file(normalized), dialogue.duration_sec, False
    )


def probe_duration_sec(probe: Mapping[str, Any]) -> float:
    raw = (probe.get("format") or {}).get("duration")
    if raw is None:
        for stream in probe.get("streams") or []:
            if stream.get("duration") is not None:
                raw = stream["duration"]
                break
    try:
        duration = float(raw)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise MediaPreparationError("SFX source has no positive duration")
    return duration


def sfx_audio_command(
    source: Path,
    output: Path,
    *,
    sample_rate: int = 48000,
    channels: int = 2,
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output),
    ]


def prepare_sfx_assets(
    hits: Sequence[Mapping[str, Any]],
    library: Mapping[str, str],
    output_dir: Path,
    *,
    request_path: Path,
    runner: CommandRunner = _default_runner,
) -> dict[str, PreparedAsset]:
    kinds = sorted({str(hit["kind"]) for hit in hits})
    output_dir.mkdir(parents=True, exist_ok=True)
    assets: dict[str, PreparedAsset] = {}
    for kind in kinds:
        value = Path(library[kind])
        source = (
            value.resolve()
            if value.is_absolute()
            else (request_path.parent / value).resolve()
        )
        if not source.is_file():
            raise MediaPreparationError(f"SFX {kind} source does not exist: {source}")
        duration = probe_duration_sec(probe_media(source, runner))
        output = output_dir / SFX_FILE_NAME[SFX_ASSET_KEY[kind]]
        _run(sfx_audio_command(source, output), runner)
        if not output.is_file():
            raise MediaPreparationError(f"SFX {kind} was not created")
        assets[SFX_ASSET_KEY[kind]] = PreparedAsset(
            output, sha256_file(output), duration, False
        )
    return assets


def composition_assets(prepared: Mapping[str, Any]) -> dict[str, Any]:
    """Contract assets for HyperFrames; insertion audio is mixed into dialogue."""
    return {
        key: value.as_contract()
        for key, value in prepared.items()
        if isinstance(value, PreparedAsset) and key != "insertionAudio"
    }


def analyze_video_metrics(
    path: Path,
    *,
    runner: CommandRunner = _default_runner,
) -> dict[str, float | int]:
    """Return supporting black/freeze/loudness measurements for Shorts QC."""
    black_command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path.resolve()),
        "-vf",
        "blackdetect=d=0.08:pix_th=0.10",
        "-f",
        "null",
        "-",
    ]
    freeze_command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path.resolve()),
        "-vf",
        "freezedetect=n=0.003:d=0.5",
        "-f",
        "null",
        "-",
    ]
    black_result = runner(black_command)
    freeze_result = runner(freeze_command)
    black_frames = len(_parse_filter_events(black_result.stderr, "blackdetect"))
    freeze_seconds = 0.0
    for event in _parse_filter_events(freeze_result.stderr, "freezedetect"):
        if "duration" in event:
            freeze_seconds += float(event["duration"])
    loudness = measure_audio_loudness(path, runner=runner)
    return {
        "blackFrames": black_frames,
        "freezeSeconds": round(freeze_seconds, 6),
        "integratedLufs": loudness["integratedLufs"],
        "truePeakDbtp": loudness["truePeakDbtp"],
    }


def validate_stream_selector(
    probe: Mapping[str, Any], selector: str, kind: str
) -> None:
    match = selector.split(":")
    if (
        len(match) != 3
        or match[0] != "0"
        or match[1] not in {"v", "a"}
        or not match[2].isdigit()
    ):
        raise MediaPreparationError(
            f"stream selector must be concrete like 0:{kind}:0: {selector}"
        )
    expected_type = "video" if kind == "v" else "audio"
    streams = [
        stream
        for stream in probe.get("streams") or []
        if stream.get("codec_type") == expected_type
    ]
    if int(match[2]) >= len(streams):
        raise MediaPreparationError(f"selected stream does not exist: {selector}")


def validate_insertion_source(
    path: Path, policy: Mapping[str, Any], *, runner: CommandRunner = _default_runner
) -> dict[str, Any]:
    if not path.is_file():
        raise MediaPreparationError(f"insertion source does not exist: {path}")
    expected = policy.get("sourceFingerprint")
    if expected and sha256_file(path) != expected:
        raise MediaPreparationError("insertion source fingerprint mismatch")
    probe = probe_media(path, runner)
    validate_stream_selector(probe, policy["videoStream"], "v")
    if policy.get("audioStream"):
        validate_stream_selector(probe, policy["audioStream"], "a")
    validate_windows(policy["approvedWindows"], policy.get("excludedWindows") or [])
    return probe


def validate_windows(
    approved: Iterable[Mapping[str, float]],
    excluded: Iterable[Mapping[str, float]],
) -> list[tuple[float, float]]:
    windows = sorted((float(w["startSec"]), float(w["endSec"])) for w in approved)
    if not windows or any(end <= start for start, end in windows):
        raise MediaPreparationError("approved insertion windows must be non-empty")
    exclusions = [(float(w["startSec"]), float(w["endSec"])) for w in excluded]
    for start, end in windows:
        if any(max(start, x0) < min(end, x1) for x0, x1 in exclusions):
            raise MediaPreparationError(
                "approved insertion window overlaps an excluded window"
            )
    return windows


def finite_repeat_map(
    approved: Iterable[Mapping[str, float]],
    target_duration: float,
) -> list[dict[str, float]]:
    windows = validate_windows(approved, [])
    if target_duration <= 0:
        raise MediaPreparationError("insertion target duration must be positive")
    result = []
    output = 0.0
    index = 0
    while output < target_duration - 1e-9:
        start, end = windows[index % len(windows)]
        take = min(end - start, target_duration - output)
        result.append(
            {
                "outputStartSec": round(output, 6),
                "outputEndSec": round(output + take, 6),
                "sourceStartSec": start,
                "sourceEndSec": round(start + take, 6),
            }
        )
        output += take
        index += 1
    return result


def validate_source_map(
    source_map: Iterable[Mapping[str, float]],
    approved: Iterable[Mapping[str, float]],
    excluded: Iterable[Mapping[str, float]],
    target_duration: float,
) -> None:
    windows = validate_windows(approved, excluded)
    cursor = 0.0
    for segment in source_map:
        if abs(float(segment["outputStartSec"]) - cursor) > 1e-5:
            raise MediaPreparationError("insertion provenance has a gap or overlap")
        s0, s1 = float(segment["sourceStartSec"]), float(segment["sourceEndSec"])
        if not any(s0 >= w0 - 1e-9 and s1 <= w1 + 1e-9 for w0, w1 in windows):
            raise MediaPreparationError("insertion provenance escapes approved windows")
        cursor = float(segment["outputEndSec"])
    if abs(cursor - target_duration) > 1e-5:
        raise MediaPreparationError(
            "insertion provenance does not cover target duration"
        )


def insertion_commands(
    source: Path,
    output_dir: Path,
    source_map: Sequence[Mapping[str, float]],
    *,
    video_stream: str,
    audio_stream: str | None,
    support_volume: float,
    fps: float = 30,
) -> tuple[list[str], list[str] | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    filters = []
    video_inputs = []
    for index, segment in enumerate(source_map):
        start, end = segment["sourceStartSec"], segment["sourceEndSec"]
        filters.append(
            f"[{video_stream}]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        video_inputs.append(f"[v{index}]")
    filters.append(
        f"{''.join(video_inputs)}concat=n={len(video_inputs)}:v=1:a=0,fps={fps},format=yuv420p[vout]"
    )
    video = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_dir / "insertion-video.mp4"),
    ]
    audio = None
    if audio_stream:
        af = [
            f"[{audio_stream}]atrim=start={s['sourceStartSec']}:end={s['sourceEndSec']},asetpts=PTS-STARTPTS[a{i}]"
            for i, s in enumerate(source_map)
        ]
        af.append(
            f"{''.join(f'[a{i}]' for i in range(len(source_map)))}concat=n={len(source_map)}:v=0:a=1,volume={support_volume},aresample=48000[aout]"
        )
        audio = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            ";".join(af),
            "-map",
            "[aout]",
            "-vn",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "aac",
            str(output_dir / "insertion-audio.m4a"),
        ]
    return video, audio


def prepare_insertion_assets(
    source: Path,
    output_dir: Path,
    *,
    approved_windows: Sequence[Mapping[str, float]],
    excluded_windows: Sequence[Mapping[str, float]],
    target_duration: float,
    video_stream: str,
    audio_stream: str | None,
    support_volume: float,
    fps: float = 30,
    runner: CommandRunner = _default_runner,
) -> tuple[dict[str, PreparedAsset], list[dict[str, float]]]:
    source_map = finite_repeat_map(approved_windows, target_duration)
    validate_source_map(source_map, approved_windows, excluded_windows, target_duration)
    video_command, audio_command = insertion_commands(
        source,
        output_dir,
        source_map,
        video_stream=video_stream,
        audio_stream=audio_stream,
        support_volume=support_volume,
        fps=fps,
    )
    _run(video_command, runner)
    assets = {}
    video = output_dir / "insertion-video.mp4"
    if not video.is_file():
        raise MediaPreparationError("insertion video was not created")
    assets["insertionVideo"] = PreparedAsset(
        video, sha256_file(video), target_duration, True
    )
    if audio_command:
        _run(audio_command, runner)
        audio = output_dir / "insertion-audio.m4a"
        if not audio.is_file():
            raise MediaPreparationError("selected insertion audio was not created")
        assets["insertionAudio"] = PreparedAsset(
            audio, sha256_file(audio), target_duration, False
        )
    return assets, source_map
