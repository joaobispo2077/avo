import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from avo import final_transcript_artifacts, render, voiceover


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", None),
        ("N/A", None),
        ("bad", None),
        ("1:2", None),
        ("1:02:03.5", 3723.5),
        ("2.5", 2.5),
    ],
)
def test_progress_time_parsing(value, expected):
    assert render._parse_ffmpeg_time(value) == expected


@pytest.mark.parametrize(
    "seconds,text", [(None, "?:??"), (-1, "0:00"), (65, "1:05"), (3661, "1:01:01")]
)
def test_progress_clock_format(seconds, text):
    assert render._format_seconds(seconds) == text


@pytest.mark.parametrize("returncode,duration", [(0, 10), (0, None), (3, 10)])
def test_progress_reports_time_and_propagates_encoder_failure(
    monkeypatch, capsys, returncode, duration
):
    proc = SimpleNamespace(
        stdout=io.StringIO(
            "out_time_ms=invalid\nout_time=00:00:02.500\nout_time_ms=5000000\nout_time=N/A\nout_time_ms=20000000\nprogress=end\n"
        ),
        wait=lambda: returncode,
    )
    popen = Mock(return_value=proc)
    monkeypatch.setattr(render.subprocess, "Popen", popen)
    if returncode:
        with pytest.raises(subprocess.CalledProcessError) as exc:
            render.run_ffmpeg_progress(["ffmpeg", "-i", "source"], "encode", duration)
        assert exc.value.returncode == 3
    else:
        render.run_ffmpeg_progress(["ffmpeg", "-i", "source"], "encode", duration)
    assert popen.call_args.args[0][:4] == ["ffmpeg", "-nostats", "-progress", "pipe:1"]
    output = capsys.readouterr().out
    assert "starting" in output
    assert ("50%" in output) == bool(duration)


@pytest.mark.parametrize(
    "probe,expected",
    [
        ("30000/1001", "30000/1001"),
        ("0/0", None),
        ("-25", None),
        ("bad", None),
        ("", None),
    ],
)
def test_probe_cadence_accepts_only_positive_rationals(monkeypatch, probe, expected):
    monkeypatch.setattr(
        render.subprocess, "run", Mock(return_value=SimpleNamespace(stdout=probe))
    )
    assert render.probe_frame_rate(Path("source")) == expected


def test_hdr_and_probe_error(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout="smpte2084\n"))
    monkeypatch.setattr(render.subprocess, "run", run)
    assert render.is_hdr_source(Path("source")) is True
    run.side_effect = subprocess.CalledProcessError(1, "ffprobe")
    assert render.is_hdr_source(Path("source")) is False
    assert render.probe_frame_rate(Path("source")) is None


@pytest.mark.parametrize(
    "mode,shape,preset",
    [
        ({}, "1920:1080", "fast"),
        ({"preview": True}, "1920:1080", "medium"),
        ({"draft": True}, "1280:720", "ultrafast"),
        ({"youtube_4k": True}, "3840:2160", "slow"),
    ],
)
def test_segment_quality_ladder_preserves_hdr_audio_and_cadence(
    tmp_path, monkeypatch, mode, shape, preset
):
    monkeypatch.delenv("AVO_RENDER_VIDEO_ENCODER", raising=False)
    monkeypatch.setattr(render, "is_hdr_source", lambda path: True)
    run = Mock()
    monkeypatch.setattr(render, "run_ffmpeg_progress", run)
    render.extract_segment(
        Path("source"),
        4,
        2,
        "eq=contrast=1.1",
        tmp_path / "out.mp4",
        frame_rate="30000/1001",
        audio_repair_filter="highpass=f=80",
        **mode,
    )
    cmd = run.call_args.args[0]
    vf = cmd[cmd.index("-vf") + 1]
    af = cmd[cmd.index("-af") + 1]
    assert f"scale={shape}" in vf and render.TONEMAP_CHAIN in vf
    assert "fps=30000/1001" in vf and vf.endswith("eq=contrast=1.1")
    assert "highpass=f=80" in af and "atrim=start=1.000:duration=2.000" in af
    assert cmd[cmd.index("-preset") + 1] == preset
    assert cmd[cmd.index("-video_track_timescale") + 1] == "30000"
    assert ("40M" in cmd) == bool(mode.get("youtube_4k"))
    assert run.call_args.kwargs["expected_duration"] == 2


@pytest.mark.parametrize(
    "preview,measurement",
    [
        (True, None),
        (False, None),
        (
            False,
            {
                "input_i": "-18",
                "input_tp": "-3",
                "input_lra": "7",
                "input_thresh": "-28",
                "target_offset": "1",
            },
        ),
    ],
)
def test_loudnorm_paths_share_lossless_picture_copy(
    tmp_path, monkeypatch, preview, measurement
):
    profile = SimpleNamespace(integrated_lufs=-16, true_peak_dbtp=-1, lra_lu=11)
    measure = Mock(return_value=measurement)
    monkeypatch.setattr(render, "measure_loudness", measure)
    monkeypatch.setattr(render, "media_duration", lambda path: 12)
    run = Mock()
    monkeypatch.setattr(render, "run_ffmpeg_progress", run)
    assert (
        render.apply_loudnorm_two_pass(
            Path("source"),
            tmp_path / "out.mp4",
            preview=preview,
            youtube_4k=True,
            profile=profile,
        )
        is True
    )
    cmd = run.call_args.args[0]
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-b:a") + 1] == "384k"
    assert cmd[cmd.index("-ar") + 1] == "48000"
    filt = cmd[cmd.index("-af") + 1]
    assert "loudnorm=I=-16:TP=-1:LRA=11" in filt and "alimiter" in filt
    assert ("measured_I=-18" in filt) == bool(measurement and not preview)
    assert measure.called != preview


@pytest.mark.parametrize(
    "mode,external,normalize",
    [
        ("default", False, True),
        ("draft", False, False),
        ("preview", False, True),
        ("youtube-4k", False, True),
        ("default", True, True),
        ("default", True, False),
    ],
)
def test_render_cli_pipeline_outputs_and_temporary_cleanup(
    tmp_path, monkeypatch, capsys, mode, external, normalize
):
    edl_path = tmp_path / "edl.json"
    edl_path.write_text("{}")
    out = tmp_path / "master.mp4"
    subs = tmp_path / "master.srt"
    subs.write_text("captions")
    edl = {
        "version": 2,
        "sources": {"camera": "camera.mp4"},
        "ranges": [{"source": "camera", "start": 1, "end": 4}],
        "overlays": [{"asset": "overlay"}],
        "sound_effects": [{"asset": "sound"}],
    }
    monkeypatch.setattr(render, "load_and_validate", Mock(return_value=edl))
    monkeypatch.setattr(render, "schema_for_edl", lambda *args: None)
    monkeypatch.setattr(render, "load_context_for_edit_dir", lambda path: ({}, {}))
    profile = SimpleNamespace(
        loudnorm_enabled=True, preset_id="reference", log_line=lambda: "target"
    )
    monkeypatch.setattr(render, "resolve_loudness_profile", Mock(return_value=profile))
    monkeypatch.setattr(render, "nr_loudness_warning", lambda *args: "NR warning")
    monkeypatch.setattr(render, "get_loudness_preset", lambda name: {})
    monkeypatch.setattr(render, "preset_stale_advisory", lambda preset: "review target")
    monkeypatch.setattr(voiceover, "is_external_voiceover_edl", lambda value: external)
    monkeypatch.setattr(voiceover, "preflight", lambda *args: [])
    extract = Mock(return_value=[tmp_path / "seg.mp4"])
    concat = Mock()
    monkeypatch.setattr(render, "extract_all_segments", extract)
    monkeypatch.setattr(render, "concat_segments", concat)

    def composite(base, overlays, subtitles, output, edit, **kwargs):
        assert subtitles == subs
        output.write_bytes(b"composite")

    build = Mock(side_effect=composite)
    mux = Mock(
        side_effect=lambda base, edl, edit, output, **kwargs: output.write_bytes(
            b"voiceover"
        )
    )
    norm = Mock(
        side_effect=lambda source, output, **kwargs: output.write_bytes(b"normalized")
    )
    monkeypatch.setattr(render, "build_final_composite", build)
    monkeypatch.setattr(render, "mux_external_voiceover", mux)
    monkeypatch.setattr(render, "apply_loudnorm_two_pass", norm)
    generated = Mock(return_value={"json": tmp_path / "transcript.json"})
    monkeypatch.setattr(final_transcript_artifacts, "generate_from_master", generated)
    argv = ["render", str(edl_path), "-o", str(out)]
    if mode != "default":
        argv.append("--" + mode)
    if not normalize:
        argv.append("--no-loudnorm")
    monkeypatch.setattr(sys, "argv", argv)
    render.main()
    assert out.read_bytes() == (
        b"normalized" if normalize else b"voiceover" if external else b"composite"
    )
    assert norm.called == normalize
    assert mux.called == external and build.called != external
    assert not out.with_suffix(".premux.mp4").exists()
    assert not out.with_suffix(".prenorm.mp4").exists()
    concat.assert_called_once()
    assert concat.call_args.kwargs["durations"] == [3]
    assert (
        concat.call_args.args[1].name
        == {
            "default": "base.mp4",
            "draft": "base_draft.mp4",
            "preview": "base_preview.mp4",
            "youtube-4k": "base_youtube_4k.mp4",
        }[mode]
    )
    assert generated.called == (mode == "youtube-4k")
    assert "done:" in capsys.readouterr().out
