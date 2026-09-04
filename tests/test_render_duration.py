from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from avo import render


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        integrated_lufs=-16.0,
        true_peak_dbtp=-1.0,
        lra_lu=9.0,
    )


def test_preview_loudnorm_bounds_render_to_shortest_stream(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], _label: str, **kwargs: object) -> None:
        captured["cmd"] = cmd
        captured["expected_duration"] = kwargs["expected_duration"]

    with (
        mock.patch("avo.render.media_duration", return_value=12.5),
        mock.patch("avo.render.run_ffmpeg_progress", side_effect=fake_run),
    ):
        render.apply_loudnorm_two_pass(
            tmp_path / "input.mp4",
            tmp_path / "output.mp4",
            profile=_profile(),
            preview=True,
        )

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd.count("-shortest") == 1
    assert captured["expected_duration"] == 12.5


def test_full_loudnorm_bounds_render_to_shortest_stream(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    measurement = {
        "input_i": "-20.0",
        "input_tp": "-3.0",
        "input_lra": "4.0",
        "input_thresh": "-30.0",
        "target_offset": "0.0",
    }

    def fake_run(cmd: list[str], _label: str, **kwargs: object) -> None:
        captured["cmd"] = cmd
        captured["expected_duration"] = kwargs["expected_duration"]

    with (
        mock.patch("avo.render.measure_loudness", return_value=measurement),
        mock.patch("avo.render.media_duration", return_value=27.25),
        mock.patch("avo.render.run_ffmpeg_progress", side_effect=fake_run),
    ):
        render.apply_loudnorm_two_pass(
            tmp_path / "input.mp4",
            tmp_path / "output.mp4",
            profile=_profile(),
            preview=False,
        )

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd.count("-shortest") == 1
    assert captured["expected_duration"] == 27.25
