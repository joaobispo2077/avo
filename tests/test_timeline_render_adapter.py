from __future__ import annotations

import sys
from pathlib import Path

from avo.adapters.media.timeline_render import TimelineRenderAdapter


def test_timeline_render_keeps_final_loudness_normalization(
    tmp_path: Path, monkeypatch
) -> None:
    projection = tmp_path / "edl.json"
    projection.write_text("{}", encoding="utf-8")
    output = tmp_path / "proof.mp4"
    captured: list[str] = []

    def fake_render() -> None:
        captured.extend(sys.argv)
        output.write_bytes(b"proof")

    monkeypatch.setattr("avo.render.main", fake_render)

    TimelineRenderAdapter().render(projection, output, profile="preview")

    assert "--no-loudnorm" not in captured
    assert "--no-subtitles" in captured
