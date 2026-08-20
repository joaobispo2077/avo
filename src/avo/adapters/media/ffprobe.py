"""ffprobe-backed raw inventory and file identity."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint


class FfprobeMediaAdapter:
    """Inventory muxed sources and expose hash, streams, clocks, and sync risk."""

    def fingerprint(self, path: Path) -> dict[str, Any]:
        return file_fingerprint(Path(path))

    def inventory(self, paths: list[Path]) -> dict[str, Any]:
        sources = [self._describe(Path(path)) for path in paths]
        clocks = {
            (
                source["durationSeconds"],
                source["streams"]["video"][0]["timeBase"]
                if source["streams"]["video"]
                else "",
                source["streams"]["audio"][0]["sampleRate"]
                if source["streams"]["audio"]
                else 0,
            )
            for source in sources
        }
        if len(sources) <= 1:
            sync_risk = {
                "status": "not-applicable",
                "reasons": ["single-muxed-clock"],
                "assessed": True,
            }
        elif len(clocks) > 1:
            sync_risk = {
                "status": "risk-detected",
                "reasons": ["multiple-source-clocks"],
                "assessed": True,
            }
        else:
            sync_risk = {
                "status": "not-applicable",
                "reasons": ["shared-muxed-clock"],
                "assessed": True,
            }
        return {"sources": sources, "syncRisk": sync_risk}

    def _describe(self, path: Path) -> dict[str, Any]:
        probe = json.loads(
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
        video: list[dict[str, Any]] = []
        audio: list[dict[str, Any]] = []
        for stream in probe.get("streams") or []:
            codec = stream.get("codec_type")
            if codec == "video":
                video.append(
                    {
                        "index": int(stream.get("index", 0)),
                        "codec": stream.get("codec_name"),
                        "width": int(stream.get("width") or 0),
                        "height": int(stream.get("height") or 0),
                        "timeBase": str(stream.get("time_base") or ""),
                    }
                )
            elif codec == "audio":
                audio.append(
                    {
                        "index": int(stream.get("index", 0)),
                        "codec": stream.get("codec_name"),
                        "sampleRate": int(stream.get("sample_rate") or 0),
                        "channels": int(stream.get("channels") or 0),
                    }
                )
        duration = float((probe.get("format") or {}).get("duration") or 0)
        return {
            "sourceId": path.stem,
            "locator": str(path),
            "fingerprint": file_fingerprint(path),
            "durationSeconds": duration,
            "streams": {"video": video, "audio": audio},
        }
