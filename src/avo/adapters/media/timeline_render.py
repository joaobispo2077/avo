"""Render a generated EDL projection through the AVO ffmpeg pipeline."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from avo.timeline.contracts import file_fingerprint


class TimelineRenderAdapter:
    """TimelineRenderPort: projection JSON in, hash-bound media out."""

    def render(self, projection: Path, output: Path, **request: Any) -> dict[str, Any]:
        from avo.render import main as render_main

        projection = Path(projection)
        output = Path(output)
        profile = str(request.get("profile") or request.get("render_profile") or "draft")
        output.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "avo.render",
            str(projection),
            "-o",
            str(output),
            "--no-subtitles",
            "--no-loudnorm",
        ]
        if profile == "draft":
            argv.append("--draft")
        elif profile == "preview":
            argv.append("--preview")
        previous = sys.argv
        try:
            sys.argv = argv
            render_main()
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise RuntimeError(f"timeline render failed: {output}") from exc
        finally:
            sys.argv = previous
        fingerprint = file_fingerprint(output)
        return {
            "status": "pass",
            "output": {**fingerprint, "locator": str(output)},
            "path": str(output),
            "renderProfile": profile,
            "producer": {"name": "avo.render", "version": "1"},
        }
