from pathlib import Path
from unittest import mock

from avo import render


def test_portrait_draft_segment_is_padded_to_landscape_canvas(tmp_path: Path) -> None:
    captured: list[str] = []

    def record(command, *_args, **_kwargs):
        captured.extend(command)

    with (
        mock.patch.object(render, "is_hdr_source", return_value=False),
        mock.patch.object(render, "run_ffmpeg_progress", side_effect=record),
    ):
        render.extract_segment(
            tmp_path / "portrait.mp4",
            0,
            2,
            "",
            tmp_path / "segment.mp4",
            draft=True,
        )

    vf = captured[captured.index("-vf") + 1]
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in vf
    assert "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black" in vf
    assert "setsar=1" in vf
    assert "trim=start=0.000:duration=2.000" in vf
    assert captured.count("-ss") == 1
    assert "-t" not in captured


def test_segment_normalizes_mixed_source_frame_rate(tmp_path: Path) -> None:
    captured: list[str] = []

    def record(command, *_args, **_kwargs):
        captured.extend(command)

    with (
        mock.patch.object(render, "is_hdr_source", return_value=False),
        mock.patch.object(render, "run_ffmpeg_progress", side_effect=record),
    ):
        render.extract_segment(
            tmp_path / "thirty-fps-insert.mp4",
            0,
            2,
            "",
            tmp_path / "segment.mp4",
            preview=True,
            frame_rate="30000/1001",
        )

    vf = captured[captured.index("-vf") + 1]
    assert "fps=30000/1001" in vf
    assert captured[captured.index("-video_track_timescale") + 1] == "30000"
    af = captured[captured.index("-af") + 1]
    assert "atrim=start=0.000:duration=2.000" in af
    assert "asetpts=PTS-STARTPTS" in af
    assert "afade=t=in:st=0:d=0.030" in af
    assert "afade=t=out:st=1.970:d=0.030" in af


def test_segment_uses_filter_trims_after_decode_lead(tmp_path: Path) -> None:
    captured: list[str] = []

    def record(command, *_args, **_kwargs):
        captured.extend(command)

    with (
        mock.patch.object(render, "is_hdr_source", return_value=False),
        mock.patch.object(render, "run_ffmpeg_progress", side_effect=record),
    ):
        render.extract_segment(
            tmp_path / "source.mp4",
            109.46,
            5.48,
            "",
            tmp_path / "segment.mp4",
            preview=True,
            frame_rate="30000/1001",
        )

    assert captured[captured.index("-ss") + 1] == "108.460"
    assert captured.count("-ss") == 1
    assert "-t" not in captured
    vf = captured[captured.index("-vf") + 1]
    af = captured[captured.index("-af") + 1]
    assert "trim=start=1.000:duration=5.480" in vf
    assert "atrim=start=1.000:duration=5.480" in af


def test_segment_can_use_nvenc_for_gpu_rendering(tmp_path: Path) -> None:
    captured: list[str] = []

    def record(command, *_args, **_kwargs):
        captured.extend(command)

    with (
        mock.patch.dict("os.environ", {"AVO_RENDER_VIDEO_ENCODER": "h264_nvenc"}),
        mock.patch.object(render, "is_hdr_source", return_value=False),
        mock.patch.object(render, "run_ffmpeg_progress", side_effect=record),
    ):
        render.extract_segment(
            tmp_path / "source.mp4",
            0,
            2,
            "",
            tmp_path / "segment.mp4",
            preview=True,
            frame_rate="30000/1001",
        )

    assert captured[captured.index("-c:v") + 1] == "h264_nvenc"
    assert "-cq" in captured
    assert "libx264" not in captured
