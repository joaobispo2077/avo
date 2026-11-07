"""Analysis algorithms and command outputs use deterministic decoded samples."""

import json
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from numpy.testing import assert_array_equal
from PIL import Image

from avo import audio_analysis as analysis
from avo import audio_eq, audio_gain, loudness_profiles


@pytest.mark.parametrize("duration", [None, 2.25])
def test_pcm_decoder_scales_signed_samples_and_removes_temporary_file(
    monkeypatch, duration
):
    outputs = []

    def decode(cmd, **kwargs):
        output = Path(cmd[-1])
        outputs.append(output)
        assert cmd[3] == "1.500"
        assert ("-t" in cmd) == (duration is not None)
        if duration is not None:
            assert cmd[cmd.index("-t") + 1] == "2.250"
        with wave.open(str(output), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(np.asarray([-32768, 0, 16384], dtype=np.int16).tobytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(analysis.subprocess, "run", decode)
    assert_array_equal(
        analysis.extract_pcm_mono(Path("source"), 1.5, duration), [-1, 0, 0.5]
    )
    assert not outputs[0].exists()


def test_pcm_failure_is_reported_and_cleaned(monkeypatch):
    outputs = []

    def decode(cmd, **kwargs):
        outputs.append(Path(cmd[-1]))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(analysis.subprocess, "run", decode)
    with pytest.raises(RuntimeError, match="Could not read audio from source"):
        analysis.extract_pcm_mono(Path("source"))
    assert not outputs[0].exists()


def test_duration_propagates_invalid_probe_output(monkeypatch):
    probe = Mock(return_value=SimpleNamespace(stdout=" 4.25\n"))
    monkeypatch.setattr(analysis.subprocess, "run", probe)
    assert analysis.media_duration(Path("source")) == 4.25
    assert probe.call_args.kwargs["check"] is True
    probe.return_value.stdout = "unknown"
    with pytest.raises(ValueError):
        analysis.media_duration(Path("source"))


@pytest.mark.parametrize(
    "score,pct", [(0.54, 35), (0.55, 50), (0.65, 60), (0.75, 70), (0.85, 75)]
)
def test_recommendation_strength_boundaries(score, pct):
    assert analysis.suggested_pct_from_score(score) == pct


def test_window_merging_preserves_maximum_score_and_disjoint_regions():
    assert analysis._merge_windows([]) == []
    assert analysis._merge_windows(
        [(4, 5, 0.6), (1, 2, 0.7), (2.25, 3, 0.9), (1.5, 1.8, 0.8)]
    ) == [(1, 3, 0.9), (4, 5, 0.6)]
    assert analysis._score_from_rms(0, 0) == 0
    assert analysis._score_from_rms(2, 1) == 1


def test_transcript_scoring_compares_noise_to_speech(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "words": [
                    {"start": 1, "end": 2, "type": "word"},
                    {"start": 2, "end": 3, "type": "spacing"},
                ]
            }
        )
    )
    pcm = np.ones(48000, dtype=np.float32) * 0.5
    pcm[16000:32000] = 0.25
    monkeypatch.setattr(analysis, "extract_pcm_mono", Mock(return_value=pcm))
    assert analysis.score_from_transcript_gaps(Path("source"), transcript, 3) == [
        (0, 1, 1),
        (2, 3, 1),
    ]
    transcript.write_text(json.dumps({"words": [{"start": 0, "end": 3}]}))
    analysis.extract_pcm_mono.reset_mock()
    assert analysis.score_from_transcript_gaps(Path("source"), transcript, 3) == []
    analysis.extract_pcm_mono.assert_not_called()
    transcript.write_text('{"words": []}')
    result = analysis.score_from_transcript_gaps(Path("source"), transcript, 3)
    assert result == []  # Whole-track RMS is below the noise/speech threshold.


@pytest.mark.parametrize("with_transcript", [True, False])
def test_suggestions_rank_round_and_assign_confidence(
    tmp_path, monkeypatch, with_transcript
):
    transcript = tmp_path / "transcript.json"
    transcript.write_text("{}")
    windows = [(1.12345, 2.23456, 0.6001), (4, 4.1, 1), (5, 6, 0.9)]
    monkeypatch.setattr(analysis, "media_duration", Mock(return_value=6))
    gaps = Mock(return_value=windows)
    sliding = Mock(return_value=windows)
    monkeypatch.setattr(analysis, "score_from_transcript_gaps", gaps)
    monkeypatch.setattr(analysis, "score_sliding_windows", sliding)
    suggestions = analysis.suggest_noise_reduction(
        Path("source"), transcript if with_transcript else None
    )
    assert [s.noise_score for s in suggestions] == [0.9, 0.6]
    assert suggestions[1].start == 1.123 and suggestions[1].end == 2.235
    assert [s.confidence for s in suggestions] == (
        ["high", "high"] if with_transcript else ["medium", "low"]
    )
    assert suggestions[0].to_dict()["reason"] == "high_hiss"
    assert gaps.called == with_transcript
    assert sliding.called != with_transcript


def test_heatmap_is_a_real_png_with_timed_noise_band(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "media_duration", lambda path: 4)
    monkeypatch.setattr(
        analysis, "compute_envelope", lambda *args, **kwargs: np.ones(1200) * 0.5
    )
    output = tmp_path / "nested" / "heatmap.png"
    analysis.render_heatmap(
        Path("source"), [analysis.NoiseSuggestion(1, 2, 0.8, 70, "high")], output
    )
    with Image.open(output) as image:
        assert image.size == (1920, 340)
        assert image.getpixel((600, 100)) == (180, 70, 40)
        assert image.getpixel((1000, 30)) == (18, 18, 22)


def test_preview_preserves_excerpt_format_and_treatment_order(tmp_path, monkeypatch):
    run = Mock()
    monkeypatch.setattr(analysis.subprocess, "run", run)
    monkeypatch.setattr(
        analysis.audio_restoration, "build_repair_filter", Mock(return_value="repair")
    )
    result = analysis.preview_segment(Path("source"), 1.25, 3.5, 60, tmp_path)
    first, second = [c.args[0] for c in run.call_args_list]
    assert first[:10] == [
        "ffmpeg",
        "-y",
        "-ss",
        "1.250",
        "-i",
        "source",
        "-t",
        "2.250",
        "-vn",
        "-ac",
    ]
    assert first[10:13] == ["2", "-ar", "48000"]
    assert first[-1] == result["before"]
    assert second == [
        "ffmpeg",
        "-y",
        "-i",
        result["before"],
        "-af",
        "repair",
        result["after"],
    ]
    assert all(c.kwargs["check"] for c in run.call_args_list)


@pytest.mark.parametrize(
    "flag,module,method,filename,heatmap",
    [
        (
            "--suggest-nr",
            analysis,
            "suggest_noise_reduction",
            "noise-reduction-suggestions.json",
            "--heatmap",
        ),
        ("--suggest-eq", audio_eq, "suggest_eq", "eq-suggestions.json", "--eq-heatmap"),
        ("--suggest-gain", audio_gain, "suggest_gain", "gain-suggestions.json", None),
    ],
)
def test_analysis_commands_write_matching_json_and_optional_heatmap(
    tmp_path, monkeypatch, capsys, flag, module, method, filename, heatmap
):
    media = tmp_path / "source.wav"
    media.touch()
    suggestion = SimpleNamespace(to_dict=lambda: {"start": 1, "end": 2})
    suggest = Mock(return_value=[suggestion])
    monkeypatch.setattr(module, method, suggest)
    render = Mock()
    if heatmap:
        monkeypatch.setattr(
            module,
            "render_heatmap" if module is analysis else "render_eq_heatmap",
            render,
        )
    output_dir = tmp_path / "reports"
    argv = [str(media), flag, "--out-dir", str(output_dir)]
    if heatmap:
        argv.append(heatmap)
    assert analysis.main(argv) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["media"] == str(media.resolve())
    assert payload["suggestions"] == [{"start": 1, "end": 2}]
    assert json.loads((output_dir / filename).read_text()) == payload
    if heatmap:
        assert render.call_args.args[:2] == (media, [suggestion])


@pytest.mark.parametrize(
    "flag,module,method,amount",
    [
        ("--preview-segment", analysis, "preview_segment", 70),
        ("--preview-gain-segment", audio_gain, "preview_gain_segment", 25),
    ],
)
def test_preview_cli_dispatch(
    tmp_path, monkeypatch, capsys, flag, module, method, amount
):
    media = tmp_path / "source.wav"
    media.touch()
    preview = Mock(return_value={"before": "a", "after": "b"})
    monkeypatch.setattr(module, method, preview)
    assert analysis.main([str(media), flag, "1", "2", "--out-dir", str(tmp_path)]) == 0
    preview.assert_called_once_with(media, 1, 2, amount, tmp_path)
    assert json.loads(capsys.readouterr().out) == {"before": "a", "after": "b"}


def test_analysis_missing_media_and_missing_action(tmp_path, capsys):
    media = tmp_path / "source.wav"
    assert analysis.main([str(media), "--suggest-nr"]) == 1
    assert "media not found" in capsys.readouterr().err
    media.touch()
    with pytest.raises(SystemExit) as exc:
        analysis.main([str(media)])
    assert exc.value.code == 2


@pytest.mark.parametrize("failure", [None, "profile", "measurement"])
def test_measure_loudness_command(tmp_path, monkeypatch, capsys, failure):
    media = tmp_path / "source.wav"
    media.touch()
    resolve = Mock(return_value=object())
    if failure == "profile":
        resolve.side_effect = ValueError("unknown preset")
    monkeypatch.setattr(loudness_profiles, "resolve_loudness_profile", resolve)
    monkeypatch.setattr(
        loudness_profiles,
        "measure_loudness",
        Mock(return_value=None if failure == "measurement" else {"input_i": "-16"}),
    )
    compare = Mock(return_value={"delta_i": 0})
    monkeypatch.setattr(loudness_profiles, "compare_measurement", compare)
    result = analysis.main(
        [str(media), "--measure-loudness", "--out-dir", str(tmp_path / "reports")]
    )
    assert result == (1 if failure else 0)
    if failure:
        assert "error:" in capsys.readouterr().err
        assert not (tmp_path / "reports").exists()
    else:
        assert json.loads(capsys.readouterr().out) == {"delta_i": 0}
        assert json.loads(
            (tmp_path / "reports" / "loudness-analysis.json").read_text()
        ) == {"delta_i": 0}
