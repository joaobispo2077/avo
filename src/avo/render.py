"""Render a video from an EDL.

Implements the HEURISTICS render pipeline in the correct order:

  1. Per-segment extract with color grade + 30ms audio fades baked in
  2. Lossless -c copy concat into base.mp4
  3. If overlays or subtitles: single filter graph that overlays animations
     (with PTS shift so frame 0 lands at the overlay window start)
     and applies `subtitles` filter LAST → final.mp4

Optionally builds a master SRT from the per-source transcripts + EDL
output-timeline offsets, applies the proven force_style (2-word
UPPERCASE chunks, Helvetica 18 Bold, MarginV=35).

Usage:
    python -m avo.render <edl.json> -o final.mp4
    python -m avo.render <edl.json> -o preview.mp4 --preview
    python -m avo.render <edl.json> -o final.mp4 --build-subtitles
    python -m avo.render <edl.json> -o final.mp4 --no-subtitles
    python -m avo.render <edl.json> -o master.mp4 --youtube-4k
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from avo.build_captions import derive_burn_in_srt
from avo.grade import auto_grade_for_clip, get_preset
from avo.paths import repo_root
from avo.validate_edl import DEFAULT_SCHEMA, EdlValidationError, load_and_validate


COMPARISON_SCHEMA = (
    repo_root()
    / "specs"
    / "003-switch-comparison-video"
    / "contracts"
    / "edl.schema.json"
)
BLURAY_PS5_SCHEMA = (
    repo_root()
    / "specs"
    / "005-bluray-ps5-gamevlog"
    / "contracts"
    / "edl.schema.json"
)


# -------- Subtitle style (bold-overlay, proven at 1920×1080 and 1080×1920) --
#
# This tutorial's creator-marked safe position is the horizontal seam between
# the two consoles, at 50% frame height. ASS Alignment=5 places the caption
# block's center at the frame center without a bottom-margin offset.
SUB_FORCE_STYLE = (
    "FontName=Helvetica,FontSize=36,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=5"
)

# -------- Helpers ------------------------------------------------------------


def run(cmd: list[str], quiet: bool = False) -> None:
    if not quiet:
        print(f"  $ {' '.join(str(c) for c in cmd[:6])}{' ...' if len(cmd) > 6 else ''}")
    subprocess.run(cmd, check=True)


def _parse_ffmpeg_time(value: str) -> float | None:
    if not value or value == "N/A":
        return None
    try:
        if ":" not in value:
            return float(value)
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (TypeError, ValueError):
        return None


def _format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "?:??"
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def run_ffmpeg_progress(
    cmd: list[str],
    label: str,
    expected_duration: float | None = None,
) -> None:
    """Run FFmpeg with compact percent progress when duration is known."""
    progress_cmd = [cmd[0], "-nostats", "-progress", "pipe:1", *cmd[1:]]
    print(f"  {label}: starting")
    proc = subprocess.Popen(
        progress_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    next_percent = 0
    last_seconds: float | None = None
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if line.startswith("out_time_ms="):
            try:
                last_seconds = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                pass
        elif line.startswith("out_time="):
            parsed = _parse_ffmpeg_time(line.split("=", 1)[1])
            if parsed is not None:
                last_seconds = parsed

        if expected_duration and last_seconds is not None:
            percent = min(100, int((last_seconds / expected_duration) * 100))
            if percent >= next_percent:
                print(
                    f"  {label}: {percent:3d}% "
                    f"({_format_seconds(last_seconds)}/{_format_seconds(expected_duration)})",
                    flush=True,
                )
                next_percent = ((percent // 5) + 1) * 5

    returncode = proc.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, progress_cmd)
    if expected_duration:
        print(f"  {label}: 100% ({_format_seconds(expected_duration)})", flush=True)


def media_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def resolve_grade_filter(grade_field: str | None) -> str:
    """The EDL's 'grade' field can be a preset name, a raw ffmpeg filter, or 'auto'.

    Returns the filter string to embed into the per-segment -vf chain.
    For 'auto', returns the sentinel "__AUTO__" which is resolved per-segment.
    """
    if not grade_field:
        return ""
    if grade_field == "auto":
        return "__AUTO__"
    # Preset names are short identifiers, filter strings contain '=' or ','.
    if re.fullmatch(r"[a-zA-Z0-9_\-]+", grade_field):
        try:
            return get_preset(grade_field)
        except KeyError:
            print(f"warning: unknown preset '{grade_field}', using as raw filter")
            return grade_field
    return grade_field


def resolve_path(maybe_path: str, base: Path) -> Path:
    """Resolve a path that may be absolute or relative to `base`."""
    p = Path(maybe_path)
    if p.is_absolute():
        return p
    return (base / p).resolve()


def source_path_value(source_record: object) -> str:
    """Return a source path from legacy string or structured source records."""
    if isinstance(source_record, dict):
        return str(source_record.get("path") or "")
    return str(source_record)


def schema_for_edl(edl_path: Path, explicit_schema: Path | None = None) -> Path:
    if explicit_schema is not None:
        return explicit_schema
    try:
        probe = json.loads(edl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SCHEMA
    if probe.get("feature_id") == "005-bluray-ps5-gamevlog":
        return BLURAY_PS5_SCHEMA
    if int(probe.get("version", 1)) >= 4 or "caption_policy" in probe:
        return COMPARISON_SCHEMA
    return DEFAULT_SCHEMA


def audio_source_stream(edl: dict) -> str:
    return str((edl.get("audio") or {}).get("main_source_stream") or "a:0")


def output_audio_channels(edl: dict) -> int:
    return int((edl.get("audio") or {}).get("output_channels") or 2)


def output_sample_rate(edl: dict) -> int:
    return int((edl.get("audio") or {}).get("sample_rate_hz") or 48000)


def audio_repair_filter_for(
    edl: dict,
    source_name: str,
    source_start: float | None = None,
    source_end: float | None = None,
) -> str:
    """Return main-camera speech cleanup chain with percent-based denoise."""
    from avo import audio_restoration

    return audio_restoration.audio_repair_filter_for(
        edl,
        source_name,
        source_start=source_start,
        source_end=source_end,
    )


def visual_subtitles_enabled(edl: dict) -> bool:
    policy = edl.get("caption_policy") or {}
    if policy.get("visual_subtitles") is False:
        if edl.get("caption_burn_in") is not None:
            raise ValueError("visual subtitles are disabled but caption_burn_in is present")
        return False
    return True


# -------- HDR → SDR tone mapping (HLG / PQ sources) --------------------------
#
# iPhone defaults to HLG HDR in Rec.2020 (and many mirrorless cameras ship PQ).
# If the source is HDR and we only downconvert bit depth (yuv420p10le → yuv420p)
# without tone-mapping, the output is 8-bit but still carries HLG/PQ transfer
# metadata. Players that honor the metadata (screen recorders, most social
# upload re-encodes) interpret 8-bit values in an HDR container and the result
# looks oversaturated / blown out. QuickTime on macOS can hide this locally —
# screen recording and uploaded renders cannot.
#
# Fix: detect HDR via color_transfer and prepend a zscale+tonemap chain to the
# vf graph so the output is clean Rec.709 SDR.

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10) and HLG

TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)


def is_hdr_source(video: Path) -> bool:
    """Return True if the source uses a PQ or HLG transfer function."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() in HDR_TRANSFERS
    except subprocess.CalledProcessError:
        return False


def is_portrait_source(video: Path) -> bool:
    """Return True if the video's height > width (portrait / vertical)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True,
        )
        w, h = map(int, out.stdout.strip().split(","))
        return h > w
    except Exception:
        return False


# -------- Per-segment extraction (Rule 2 + Rule 3) --------------------------


def extract_segment(
    source: Path,
    seg_start: float,
    duration: float,
    grade_filter: str,
    out_path: Path,
    preview: bool = False,
    draft: bool = False,
    youtube_4k: bool = False,
    youtube_4k_preset: str = "slow",
    audio_stream: str = "a:0",
    audio_repair_filter: str = "",
) -> None:
    """Extract a cut range as its own MP4 with grade + 30ms audio fades baked in.

    `-ss` before `-i` for fast accurate seeking. Scale to 1080p from 4K.
    Portrait sources (height > width) are scaled by height to preserve orientation.

    Quality ladder:
      - final (default): 1080p libx264 fast CRF 20
      - youtube_4k:       2160p H.264 high profile VBR 40M, AAC stereo 384k,
                          preserving the source frame rate
      - preview:         1080p libx264 medium CRF 22 (evaluable for QC)
      - draft:           720p libx264 ultrafast CRF 28 (cut-point check only)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    portrait = is_portrait_source(source)
    if draft:
        scale = "scale=-2:1280" if portrait else "scale=1280:-2"
    elif youtube_4k:
        scale = "scale=-2:3840" if portrait else "scale=3840:-2"
    else:
        scale = "scale=-2:1920" if portrait else "scale=1920:-2"

    vf_parts: list[str] = []
    if is_hdr_source(source):
        vf_parts.append(TONEMAP_CHAIN)
    vf_parts.append(scale)
    if grade_filter:
        vf_parts.append(grade_filter)
    vf = ",".join(vf_parts)

    # 30ms audio fades at both edges (Rule 3) — prevent pops
    fade_out_start = max(0.0, duration - 0.03)
    af_parts = []
    if audio_repair_filter:
        af_parts.append(audio_repair_filter)
    af_parts.append(f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_start:.3f}:d=0.03")
    af = ",".join(af_parts)

    if draft:
        preset, crf = "ultrafast", "28"
    elif preview:
        preset, crf = "medium", "22"
    elif youtube_4k:
        preset, crf = youtube_4k_preset, "17"
    else:
        preset, crf = "fast", "20"

    audio_bitrate = "384k" if youtube_4k else "192k"

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg_start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-af", af,
        "-map", "0:v:0",
        "-map", f"0:{audio_stream}",
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        # YouTube deliverables are stereo. FFmpeg duplicates mono sources to
        # centered dual-mono while leaving native stereo channel selection intact.
        "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(out_path),
    ]
    if youtube_4k:
        cmd[-3:-3] = ["-b:v", "40M", "-maxrate", "45M", "-bufsize", "90M"]
    run_ffmpeg_progress(cmd, f"segment {out_path.name}", expected_duration=duration)


def extract_all_segments(
    edl: dict,
    edit_dir: Path,
    preview: bool,
    draft: bool = False,
    youtube_4k: bool = False,
    youtube_4k_preset: str = "slow",
    resume_existing: bool = False,
) -> list[Path]:
    """Extract every EDL range into edit_dir/clips_graded/seg_NN.mp4.
    Returns the ordered list of segment paths.

    If the EDL `grade` is "auto", analyze each segment range with
    `auto_grade_for_clip` and apply a per-segment subtle correction.
    Otherwise, apply the same preset/raw filter to every segment.
    """
    resolved = resolve_grade_filter(edl.get("grade"))
    is_auto = resolved == "__AUTO__"
    clips_dir = edit_dir / (
        "clips_draft"
        if draft
        else ("clips_preview" if preview else ("clips_youtube_4k" if youtube_4k else "clips_graded"))
    )
    clips_dir.mkdir(parents=True, exist_ok=True)

    ranges = edl["ranges"]
    sources = edl["sources"]

    seg_paths: list[Path] = []
    print(f"extracting {len(ranges)} segment(s) -> {clips_dir.name}/")
    if is_auto:
        print("  (auto-grade per segment: analyzing each range)")
    for i, r in enumerate(ranges):
        src_name = r["source"]
        src_path = resolve_path(source_path_value(sources[src_name]), edit_dir)
        start = float(r["start"])
        end = float(r["end"])
        duration = end - start
        out_path = clips_dir / f"seg_{i:02d}_{src_name}.mp4"

        if is_auto:
            seg_filter, _stats = auto_grade_for_clip(src_path, start=start, duration=duration, verbose=False)
        else:
            seg_filter = resolved

        note = r.get("beat") or r.get("note") or ""
        print(f"  [{i:02d}] {src_name}  {start:7.2f}-{end:7.2f}  ({duration:5.2f}s)  {note}")
        if is_auto:
            print(f"        grade: {seg_filter or '(none)'}")
        existing_duration = media_duration(out_path) if resume_existing and out_path.exists() else None
        if (
            resume_existing
            and existing_duration is not None
            and abs(existing_duration - duration) <= 0.25
        ):
            print(f"        resume: reusing existing {out_path.name} ({existing_duration:.2f}s)")
            seg_paths.append(out_path)
            continue
        extract_segment(
            src_path,
            start,
            duration,
            seg_filter,
            out_path,
            preview=preview,
            draft=draft,
            youtube_4k=youtube_4k,
            youtube_4k_preset=youtube_4k_preset,
            audio_stream=audio_source_stream(edl),
            audio_repair_filter=audio_repair_filter_for(edl, src_name, start, end),
        )
        seg_paths.append(out_path)

    return seg_paths


# -------- Lossless concat ----------------------------------------------------


def concat_segments(segment_paths: list[Path], out_path: Path, edit_dir: Path) -> None:
    """Lossless concat via the concat demuxer. No re-encode."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = edit_dir / "_concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in segment_paths),
        encoding="utf-8",
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"concat -> {out_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    concat_list.unlink(missing_ok=True)


# -------- Master SRT (Rule 5) ------------------------------------------------


PUNCT_BREAK = set(".,!?;:")


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_in_range(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    out: list[dict] = []
    for w in transcript.get("words", []):
        if w.get("type") != "word":
            continue
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if we <= t_start or ws >= t_end:
            continue
        out.append(w)
    return out


def build_master_srt(edl: dict, edit_dir: Path, out_path: Path) -> None:
    """Build an output-timeline SRT from per-source transcripts.

    - 2-word chunks (break on any punctuation in between)
    - UPPERCASE text
    - Output times computed as word.start - segment_start + segment_offset
    """
    transcripts_dir = edit_dir / "transcripts"
    sources = edl["sources"]

    entries: list[tuple[float, float, str]] = []
    seg_offset = 0.0

    for r in edl["ranges"]:
        src_name = r["source"]
        seg_start = float(r["start"])
        seg_end = float(r["end"])
        seg_duration = seg_end - seg_start

        tr_path = transcripts_dir / f"{src_name}.json"
        if not tr_path.exists():
            print(f"  no transcript for {src_name}, skipping captions for this segment")
            seg_offset += seg_duration
            continue

        transcript = json.loads(tr_path.read_text(encoding="utf-8"))
        words_in_seg = _words_in_range(transcript, seg_start, seg_end)

        # Group into 2-word chunks, break on punctuation
        chunks: list[list[dict]] = []
        current: list[dict] = []
        for w in words_in_seg:
            text = (w.get("text") or "").strip()
            if not text:
                continue
            current.append(w)
            # Break if the current text ends in punctuation or we hit 2 words
            ends_in_punct = bool(text) and text[-1] in PUNCT_BREAK
            if len(current) >= 2 or ends_in_punct:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        for chunk in chunks:
            local_start = max(seg_start, chunk[0].get("start", seg_start))
            local_end = min(seg_end, chunk[-1].get("end", seg_end))
            out_start = max(0.0, local_start - seg_start) + seg_offset
            out_end = max(0.0, local_end - seg_start) + seg_offset
            if out_end <= out_start:
                out_end = out_start + 0.4
            text = " ".join((w.get("text") or "").strip() for w in chunk)
            text = re.sub(r"\s+", " ", text).strip()
            # The creator requested no terminal periods in any caption form.
            text = text.rstrip(".")
            text = text.upper()
            entries.append((out_start, out_end, text))

        seg_offset += seg_duration

    # Sort and write as SRT
    entries.sort(key=lambda e: e[0])
    lines: list[str] = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(a)} --> {_srt_timestamp(b)}")
        lines.append(t)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"master SRT -> {out_path.name} ({len(entries)} cues)")


# -------- Loudness normalization (social-ready audio) -----------------------


# Social-media standard: -14 LUFS integrated, -1 dBTP peak, LRA 11 LU.
# Matches YouTube / Instagram / TikTok / X / LinkedIn normalization targets.
LOUDNORM_I = -16.0
LOUDNORM_TP = -3.0
LOUDNORM_LRA = 7.0
LIMITER_FILTER = "alimiter=limit=0.630:level=false:attack=5:release=50"


def measure_loudness(video_path: Path) -> dict[str, str] | None:
    """Run ffmpeg loudnorm first pass and parse the JSON measurement.

    Returns a dict with measured_i, measured_tp, measured_lra, measured_thresh,
    target_offset, or None if measurement failed.
    """
    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(video_path),
        "-af", filter_str,
        "-vn", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # loudnorm prints the JSON to stderr at the end of the run
    stderr = proc.stderr

    # Find the JSON block — loudnorm output contains a `{ ... }` block
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not needed.issubset(data.keys()):
        return None
    return data


def apply_loudnorm_two_pass(
    input_path: Path,
    output_path: Path,
    preview: bool = False,
    youtube_4k: bool = False,
) -> bool:
    """Run two-pass loudnorm on input_path, write normalized copy to output_path.

    Returns True on success, False if measurement failed (caller should fall
    back to copying the input unchanged).

    In preview mode, skips the measurement pass and uses a one-pass approximation
    for speed. Final mode always does the proper two-pass.
    """
    audio_bitrate = "384k" if youtube_4k else "192k"

    if preview:
        # One-pass approximation — faster, slightly less accurate.
        filter_str = (
            f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA},"
            f"{LIMITER_FILTER}"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", filter_str,
            "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000",
            "-movflags", "+faststart",
            str(output_path),
        ]
        print(f"  loudnorm (1-pass preview) -> {output_path.name}")
        run_ffmpeg_progress(cmd, f"loudnorm {output_path.name}", expected_duration=media_duration(input_path))
        return True

    # Full two-pass
    print(f"  loudnorm pass 1: measuring {input_path.name}")
    measurement = measure_loudness(input_path)
    if measurement is None:
        print("  loudnorm measurement failed — falling back to 1-pass")
        return apply_loudnorm_two_pass(
            input_path,
            output_path,
            preview=True,
            youtube_4k=youtube_4k,
        )

    print(f"    measured: I={measurement['input_i']} LUFS  "
          f"TP={measurement['input_tp']}  LRA={measurement['input_lra']}")

    loudnorm_filter = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        f":measured_I={measurement['input_i']}"
        f":measured_TP={measurement['input_tp']}"
        f":measured_LRA={measurement['input_lra']}"
        f":measured_thresh={measurement['input_thresh']}"
        f":offset={measurement['target_offset']}"
        f":linear=true"
    )
    filter_str = f"{loudnorm_filter},{LIMITER_FILTER}"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-c:v", "copy",
        "-af", filter_str,
        "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ]
    print(f"  loudnorm pass 2: normalizing -> {output_path.name}")
    run_ffmpeg_progress(cmd, f"loudnorm {output_path.name}", expected_duration=media_duration(input_path))
    return True


# -------- Final compositing (Rule 1 + Rule 4) -------------------------------


def build_overlay_filter_parts(
    overlays: list[dict],
    first_input_index: int = 1,
    overlay_scale: str | None = None,
) -> tuple[list[str], str]:
    """Build alpha-overlay filters and return parts plus the current video label."""
    parts: list[str] = []
    current = "[0:v]"
    for offset, overlay in enumerate(overlays):
        input_index = first_input_index + offset
        sequence = offset + 1
        start = float(overlay["start_in_output"])
        duration = float(overlay["duration"])
        end = start + duration
        shifted = f"[a{sequence}]"
        output = f"[v{sequence}]"
        overlay_chain = f"[{input_index}:v]format=yuva420p,"
        if overlay_scale:
            overlay_chain += f"scale={overlay_scale},"
        # Limit overlay streams to their approved EDL window. Without this,
        # a longer reusable overlay asset can extend the output timeline even
        # when the overlay filter's enable window has already ended.
        overlay_chain += f"trim=duration={duration:.3f},setpts=PTS-STARTPTS+{start:g}/TB{shifted}"
        parts.append(overlay_chain)
        parts.append(
            f"{current}{shifted}"
            f"overlay=enable='between(t,{start:.3f},{end:.3f})'{output}"
        )
        current = output
    return parts, current


def _subtitle_filter_path(path: Path) -> str:
    return (
        str(path.resolve())
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )


def build_subtitle_filter(input_label: str, subtitles_path: Path) -> str:
    """Build the caption-last video filter for the first-minute SRT."""
    escaped = _subtitle_filter_path(subtitles_path)
    return (
        f"{input_label}subtitles='{escaped}':"
        f"force_style='{SUB_FORCE_STYLE}'[outv]"
    )


def build_audio_filter_parts(
    sound_effects: list[dict],
    first_input_index: int,
) -> tuple[list[str], str]:
    """Build a centered stereo speech mix with delayed, subordinate SFX."""
    if not sound_effects:
        return [], "0:a:0"

    parts = [
        "[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo[basea]"
    ]
    labels = ["[basea]"]
    for offset, effect in enumerate(sound_effects):
        input_index = first_input_index + offset
        sequence = offset + 1
        delay_ms = int(round(float(effect["start_in_output"]) * 1000))
        duration = float(effect["duration"])
        gain = float(effect["gain_db"])
        label = f"[sfx{sequence}]"
        parts.append(
            f"[{input_index}:a:0]"
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
            f"volume={gain:.3f}dB,adelay={delay_ms}|{delay_ms}{label}"
        )
        labels.append(label)
    parts.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:"
        "normalize=0[outa]"
    )
    return parts, "[outa]"


def build_final_composite(
    base_path: Path,
    overlays: list[dict],
    subtitles_path: Path | None,
    out_path: Path,
    edit_dir: Path,
    sound_effects: list[dict] | None = None,
    youtube_4k: bool = False,
    youtube_4k_preset: str = "slow",
) -> None:
    """Final pass: base -> overlays/SFX -> first-minute captions last -> output.

    Overlay inputs must carry alpha. Sound effects are delayed on the output
    timeline and mixed below the base speech before final loudness treatment.
    """
    sound_effects = sound_effects or []
    has_overlays = bool(overlays)
    has_subs = subtitles_path is not None and subtitles_path.exists()
    has_sfx = bool(sound_effects)

    if not has_overlays and not has_subs and not has_sfx:
        run(["ffmpeg", "-y", "-i", str(base_path), "-c", "copy", str(out_path)], quiet=True)
        return

    inputs: list[str] = ["-i", str(base_path)]
    for overlay in overlays:
        inputs += ["-i", str(resolve_path(overlay["file"], edit_dir))]
    for effect in sound_effects:
        inputs += ["-i", str(resolve_path(effect["file"], edit_dir))]

    video_parts, current_video = build_overlay_filter_parts(
        overlays,
        overlay_scale="3840:2160" if youtube_4k else None,
    )

    if has_subs:
        video_parts.append(build_subtitle_filter(current_video, subtitles_path))
        video_output = "[outv]"
    elif has_overlays:
        video_parts.append(f"{current_video}null[outv]")
        video_output = "[outv]"
    else:
        video_output = "0:v:0"

    first_sfx_input = 1 + len(overlays)
    audio_parts, audio_output = build_audio_filter_parts(
        sound_effects,
        first_input_index=first_sfx_input,
    )
    filter_parts = video_parts + audio_parts

    cmd = [
        "ffmpeg", "-y",
        *inputs,
    ]
    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts)]
    cmd += [
        "-map", video_output,
        "-map", audio_output,
        "-c:v", "libx264", "-preset", youtube_4k_preset if youtube_4k else "fast",
    ]
    if youtube_4k:
        cmd += ["-b:v", "40M", "-maxrate", "45M", "-bufsize", "90M"]
    else:
        cmd += ["-crf", "18"]
    cmd += [
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-c:a", "aac" if has_sfx else "copy",
    ]
    if has_sfx:
        cmd += ["-b:a", "384k" if youtube_4k else "192k", "-ar", "48000", "-ac", "2"]
    cmd += ["-movflags", "+faststart", str(out_path)]
    print(f"compositing -> {out_path.name}")
    print(
        f"  overlays: {len(overlays)}, sfx: {len(sound_effects)}, "
        f"burned captions: {'yes' if has_subs else 'no'}"
    )
    run_ffmpeg_progress(cmd, f"composite {out_path.name}", expected_duration=media_duration(base_path))


# -------- Main ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a video from an EDL")
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output video path")
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 1080p, medium, CRF 22 — evaluable for QC, faster than final.",
    )
    ap.add_argument(
        "--draft",
        action="store_true",
        help="Draft mode: 720p, ultrafast, CRF 28 — cut-point verification only.",
    )
    ap.add_argument(
        "--build-subtitles",
        action="store_true",
        help="Build master.srt from transcripts + EDL offsets before compositing",
    )
    ap.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Skip subtitles even if the EDL references one",
    )
    ap.add_argument(
        "--no-loudnorm",
        action="store_true",
        help="Skip audio treatment. Default is on (-16 LUFS, peak-safe limiter, LRA 7).",
    )
    ap.add_argument(
        "--youtube-4k",
        action="store_true",
        help="Render 3840x2160 SDR H.264 for YouTube, using 40M video and 384k stereo AAC.",
    )
    ap.add_argument(
        "--youtube-4k-preset",
        choices=("fast", "medium", "slow"),
        default="slow",
        help="libx264 preset for --youtube-4k. Default keeps the prior slow setting.",
    )
    ap.add_argument(
        "--resume-existing",
        action="store_true",
        help="Reuse existing extracted segment files when their duration matches the EDL range.",
    )
    ap.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Optional EDL schema path. Auto-detects the comparison v4 schema when omitted.",
    )
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl not found: {edl_path}")

    try:
        edl = load_and_validate(edl_path, schema_path=schema_for_edl(edl_path, args.schema))
    except (EdlValidationError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))
    edit_dir = edl_path.parent
    out_path = args.output.resolve()
    version = int(edl.get("version", 1))

    # 1. Extract per-segment (auto-grade per range if EDL grade is "auto")
    segment_paths = extract_all_segments(
        edl,
        edit_dir,
        preview=args.preview,
        draft=args.draft,
        youtube_4k=args.youtube_4k,
        youtube_4k_preset=args.youtube_4k_preset,
        resume_existing=args.resume_existing,
    )

    # 2. Concat → base
    if args.draft:
        base_name = "base_draft.mp4"
    elif args.preview:
        base_name = "base_preview.mp4"
    elif args.youtube_4k:
        base_name = "base_youtube_4k.mp4"
    else:
        base_name = "base.mp4"
    base_path = edit_dir / base_name
    concat_segments(segment_paths, base_path, edit_dir)

    # 3. Captions: keep the complete selectable SRT, but burn only the
    # first-minute derived file for EDL v3.
    subs_path: Path | None = None
    if not args.no_subtitles:
        full_subs_path = (
            resolve_path(edl["subtitles"], edit_dir)
            if edl.get("subtitles")
            else edit_dir / "master.srt"
        )
        if args.build_subtitles:
            build_master_srt(edl, edit_dir, full_subs_path)

        if visual_subtitles_enabled(edl):
            if version >= 3 and edl.get("caption_burn_in"):
                burn_config = edl["caption_burn_in"]
                subs_path = resolve_path(burn_config["file"], edit_dir)
                if args.build_subtitles:
                    derive_burn_in_srt(
                        full_subs_path,
                        subs_path,
                        end_seconds=float(burn_config["end_in_output"]),
                    )
            elif "caption_policy" not in edl:
                subs_path = full_subs_path

        if subs_path is not None:
            if not subs_path.exists():
                print(f"warning: subtitles path in EDL does not exist: {subs_path}")
                subs_path = None

    # 4. Composite overlays and SFX, then burn first-minute captions last.
    overlays = edl.get("overlays") or []
    sound_effects = edl.get("sound_effects") or []
    if args.no_loudnorm:
        build_final_composite(
            base_path,
            overlays,
            subs_path,
            out_path,
            edit_dir,
            sound_effects=sound_effects,
            youtube_4k=args.youtube_4k,
            youtube_4k_preset=args.youtube_4k_preset,
        )
    else:
        tmp_composite = out_path.with_suffix(".prenorm.mp4")
        build_final_composite(
            base_path,
            overlays,
            subs_path,
            tmp_composite,
            edit_dir,
            sound_effects=sound_effects,
            youtube_4k=args.youtube_4k,
            youtube_4k_preset=args.youtube_4k_preset,
        )
        print("audio treatment -> -16 LUFS / -3 dBTP target / LRA 7 / peak-safe limiter")
        apply_loudnorm_two_pass(
            tmp_composite,
            out_path,
            preview=args.draft,
            youtube_4k=args.youtube_4k,
        )
        tmp_composite.unlink(missing_ok=True)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\ndone: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
