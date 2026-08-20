"""Apply approved Sync transforms to raw picture and audio exactly once."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint

SYNC_COMMENT_PREFIX = "avo-sync-materialized:"


class SyncMaterializationError(ValueError):
    """Raised when sync materialization would be unsafe or repeated."""


@dataclass(frozen=True)
class AudioFilterPlan:
    filter_complex: str
    output_label: str


def _ticks_to_seconds(ticks: int, timebase: dict[str, Any]) -> float:
    return (
        float(ticks) * float(timebase.get("num", 1)) / float(timebase.get("den", 1000))
    )


def _probe(path: Path) -> dict[str, Any]:
    return json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def _comment(path: Path) -> str:
    try:
        tags = (_probe(path).get("format") or {}).get("tags") or {}
    except Exception:
        return ""
    return str(tags.get("comment") or tags.get("COMMENT") or "")


def _duration(path: Path) -> float:
    return float((_probe(path).get("format") or {}).get("duration") or 0)


class SyncMaterializer:
    def validate_inputs(
        self,
        picture_path: Path,
        audio_path: Path,
        *,
        picture_kind: str = "raw",
        audio_kind: str = "raw",
        expected_picture_sha256: str | None = None,
        expected_audio_sha256: str | None = None,
    ) -> None:
        if picture_kind != "raw" or audio_kind != "raw":
            raise SyncMaterializationError(
                "sync materialization must start from raw sources"
            )
        picture = file_fingerprint(Path(picture_path))
        audio = file_fingerprint(Path(audio_path))
        if expected_picture_sha256 and picture["sha256"] != expected_picture_sha256:
            raise SyncMaterializationError("picture fingerprint mismatch")
        if expected_audio_sha256 and audio["sha256"] != expected_audio_sha256:
            raise SyncMaterializationError("audio fingerprint mismatch")

    def compile_audio_filter(self, transform: dict[str, Any]) -> AudioFilterPlan:
        kind = str(transform.get("kind") or "")
        timebase = transform.get("timebase") or {"num": 1, "den": 1000}
        chain: list[str] = []
        if kind == "constant-offset":
            seconds = _ticks_to_seconds(
                int(transform.get("offsetTicks") or 0), timebase
            )
            if seconds >= 0:
                delay_ms = round(seconds * 1000)
                chain.append(f"adelay={delay_ms}|{delay_ms}")
            else:
                chain.append(f"atrim=start={-seconds:.3f}")
                chain.append("asetpts=PTS-STARTPTS")
        elif kind == "linear-drift":
            ratio = transform.get("rateRatio") or {"num": 1, "den": 1}
            num = max(1, int(ratio.get("num") or 1))
            den = max(1, int(ratio.get("den") or 1))
            chain.append(f"asetrate=48000*{num}/{den}")
            chain.append("aresample=48000")
        elif kind == "piecewise":
            chain.append("aresample=48000")
        else:
            raise SyncMaterializationError(f"unsupported sync transform: {kind}")
        chain.append("aformat=sample_rates=48000:channel_layouts=mono")
        body = ",".join(chain)
        return AudioFilterPlan(
            filter_complex=f"[0:a]{body}[synca]",
            output_label="synca",
        )

    def materialize(
        self,
        *,
        picture_path: Path,
        audio_path: Path,
        output_path: Path,
        transform: dict[str, Any],
        sync_revision_hash: str,
        expected_picture_sha256: str | None = None,
        expected_audio_sha256: str | None = None,
    ) -> dict[str, Any]:
        picture_path = Path(picture_path)
        audio_path = Path(audio_path)
        output_path = Path(output_path)
        self.validate_inputs(
            picture_path,
            audio_path,
            expected_picture_sha256=expected_picture_sha256,
            expected_audio_sha256=expected_audio_sha256,
        )
        if _comment(picture_path).startswith(SYNC_COMMENT_PREFIX) or _comment(
            audio_path
        ).startswith(SYNC_COMMENT_PREFIX):
            raise SyncMaterializationError("already sync-materialized")
        plan = self.compile_audio_filter(transform)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = _duration(picture_path)
        same = picture_path.resolve() == audio_path.resolve()
        audio_ref = "[0:a]" if same else "[1:a]"
        filter_complex = plan.filter_complex.replace("[0:a]", audio_ref)
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(picture_path),
        ]
        if not same:
            cmd += ["-i", str(audio_path)]
        cmd += [
            "-filter_complex",
            f"[0:v]setpts=PTS-STARTPTS[v];{filter_complex}",
            "-map",
            "[v]",
            "-map",
            f"[{plan.output_label}]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-metadata",
            f"comment={SYNC_COMMENT_PREFIX}{sync_revision_hash}",
            "-movflags",
            "+faststart",
        ]
        if duration > 0:
            cmd += ["-t", f"{duration:.3f}"]
        cmd.append(str(output_path))
        subprocess.run(cmd, check=True, capture_output=True)
        return {
            "appliedExactlyOnce": True,
            "output": file_fingerprint(output_path),
            "syncRevisionHash": sync_revision_hash,
            "transform": transform,
        }
