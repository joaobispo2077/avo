import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from avo import audio_qc, init_project, loudness_profiles


@pytest.mark.parametrize("status,legacy", [("PASS", False), ("FAIL", True)])
def test_qc_reports_exit_status_upload_comparison_and_legacy_warning(
    tmp_path, monkeypatch, capsys, status, legacy
):
    master = tmp_path / "master.wav"
    upload = tmp_path / "upload.mp4"
    master.touch()
    upload.touch()
    profile = SimpleNamespace(
        legacy_warning=legacy,
        preset_label="reference",
        to_dict=lambda: {"intent": "platform_fit"},
    )
    monkeypatch.setattr(
        loudness_profiles, "resolve_loudness_profile", Mock(return_value=profile)
    )
    measure = Mock(side_effect=[{"input_tp": "-2"}, {"input_tp": "-1.8"}])
    monkeypatch.setattr(loudness_profiles, "measure_loudness", measure)
    evaluate = Mock(return_value={"status": status})
    monkeypatch.setattr(loudness_profiles, "evaluate_qc", evaluate)
    output = tmp_path / "nested" / "qc.json"
    assert audio_qc.main(
        [str(master), "--upload-candidate", str(upload), "--out", str(output)]
    ) == (0 if status == "PASS" else 2)
    payload = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text()) == payload
    assert payload["master"] == str(master.resolve())
    assert payload["profile"] == {"intent": "platform_fit"}
    assert ("legacy_warning" in payload["qc"]) == legacy
    evaluate.assert_called_once_with(
        {"input_tp": "-2"}, profile, upload_measurement={"input_tp": "-1.8"}
    )
    assert [c.args[0] for c in measure.call_args_list] == [master, upload]


@pytest.mark.parametrize(
    "failure,message",
    [
        ("master", "master not found"),
        ("profile", "unknown target"),
        ("measurement", "measurement failed"),
        ("upload", "upload candidate not found"),
    ],
)
def test_qc_failures_do_not_write_a_report(
    tmp_path, monkeypatch, capsys, failure, message
):
    master = tmp_path / "master.wav"
    if failure != "master":
        master.touch()
    resolve = Mock(
        return_value=object(),
        side_effect=ValueError("unknown target") if failure == "profile" else None,
    )
    monkeypatch.setattr(loudness_profiles, "resolve_loudness_profile", resolve)
    monkeypatch.setattr(
        loudness_profiles,
        "measure_loudness",
        Mock(return_value=None if failure == "measurement" else {"input_i": "-16"}),
    )
    output = tmp_path / "qc.json"
    argv = [str(master), "--out", str(output)]
    if failure == "upload":
        argv.extend(["--upload-candidate", str(tmp_path / "absent")])
    assert audio_qc.main(argv) == 1
    assert message in capsys.readouterr().err
    assert not output.exists()


def test_loudness_inputs_prefer_explicit_project_then_edl_parent(tmp_path, monkeypatch):
    edit = tmp_path / "edit"
    edit.mkdir()
    edl = edit / "edl.json"
    edl.write_text('{"audio": {"loudness_preset": "youtube_shorts"}}')
    implicit = tmp_path / "avo.project.json"
    implicit.write_text('{"provider": "implicit"}')
    explicit = tmp_path / "custom.json"
    explicit.write_text('{"provider": "explicit"}')
    load = Mock(side_effect=lambda slug: {"slug": slug})
    monkeypatch.setattr(init_project, "load_provider", load)
    edl_data, project, provider = loudness_profiles.load_context_for_inputs(
        edl, explicit
    )
    assert edl_data["audio"]["loudness_preset"] == "youtube_shorts"
    assert project == {"provider": "explicit"} and provider == {"slug": "explicit"}
    assert loudness_profiles.load_context_for_inputs(edl, tmp_path / "missing")[1:] == (
        {"provider": "implicit"},
        {"slug": "implicit"},
    )
    assert loudness_profiles.load_context_for_inputs(None, None) == ({}, {}, {})
    edl.unlink()
    load.side_effect = FileNotFoundError("provider missing")
    assert loudness_profiles.load_context_for_inputs(edl, None) == (
        {},
        {"provider": "implicit"},
        {},
    )


def test_invalid_context_json_is_not_silently_replaced(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        loudness_profiles.load_context_for_inputs(invalid, None)
