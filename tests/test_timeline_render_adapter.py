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


def test_timeline_render_uses_contract_dimensions_to_select_4k(
    tmp_path: Path, monkeypatch
) -> None:
    projection = tmp_path / "edl.json"
    projection.write_text("{}", encoding="utf-8")
    output = tmp_path / "master.mp4"
    captured: list[str] = []

    def fake_render() -> None:
        captured.extend(sys.argv)
        output.write_bytes(b"master")

    monkeypatch.setattr("avo.render.main", fake_render)
    monkeypatch.setattr(
        TimelineRenderAdapter,
        "_probe_output",
        staticmethod(
            lambda _path: {"width": 3840, "height": 2160, "frameRate": 30000 / 1001}
        ),
    )

    result = TimelineRenderAdapter().render(
        projection,
        output,
        profile="master",
        render_contract={
            "width": 3840,
            "height": 2160,
            "frameRate": {"num": 30000, "den": 1001, "tolerance": 0.001},
        },
    )

    assert "--youtube-4k" in captured
    assert result["media"]["width"] == 3840


def test_timeline_render_rejects_geometry_that_disagrees_with_contract(
    tmp_path: Path, monkeypatch
) -> None:
    projection = tmp_path / "edl.json"
    projection.write_text("{}", encoding="utf-8")
    output = tmp_path / "proof.mp4"

    def fake_render() -> None:
        output.write_bytes(b"proof")

    monkeypatch.setattr("avo.render.main", fake_render)
    monkeypatch.setattr(
        TimelineRenderAdapter,
        "_probe_output",
        staticmethod(lambda _path: {"width": 1920, "height": 1080, "frameRate": 30}),
    )

    try:
        TimelineRenderAdapter().render(
            projection,
            output,
            profile="preview",
            render_contract={
                "width": 1280,
                "height": 720,
                "frameRate": {"num": 30000, "den": 1001, "tolerance": 0.001},
            },
        )
    except RuntimeError as exc:
        assert "width, height, frameRate" in str(exc)
    else:
        raise AssertionError("contract mismatch must fail")
