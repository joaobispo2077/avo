"""Current and historic report routing without paid calls."""

import json

from avo.cli import main
from test_costs import fact


def project(tmp_path):
    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps({"rawDir": str(tmp_path), "provider": "channel", "videoId": "video"})
    )
    return path


def test_report_alias_read_only(tmp_path, capsys):
    path = project(tmp_path)
    assert main(["costs", "--project", str(path), "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["metrics", "--project", str(path), "--json"]) == 0
    assert first == json.loads(capsys.readouterr().out)
    assert not (tmp_path / "edit").exists()


def test_explicit_project_before_operation_is_preserved(tmp_path, capsys):
    path = project(tmp_path)
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact()]))
    assert (
        main(
            ["costs", "--project", str(path), "--json", "import", "--file", str(source)]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["imported"] == 1


def test_import_report_price_and_history(tmp_path, capsys):
    path = project(tmp_path)
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact()]))
    assert (
        main(
            ["costs", "import", "--project", str(path), "--file", str(source), "--json"]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["costs", "--project", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tokens"]["total"] == 120
    assert (
        main(
            ["costs", "snapshot", "--project", str(path), "--stage", "final", "--json"]
        )
        == 2
    )
    assert "cleanup" in capsys.readouterr().err


def test_corrupt_input_is_sanitized(tmp_path, capsys):
    path = project(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"prompt":"PRIVATE", "broken":}')
    assert main(["costs", "import", "--project", str(path), "--file", str(bad)]) == 2
    assert "PRIVATE" not in capsys.readouterr().err


def test_history_default_is_readable_not_raw_evidence(monkeypatch, capsys):
    from avo import cost_history

    video = {
        "provider": "channel",
        "videoId": "video",
        "amounts": [],
        "tokens": {"total": 120},
        "coverage": "partial",
        "cutoff": None,
    }
    monkeypatch.setattr(
        cost_history,
        "history",
        lambda **_: {"videos": [video], "diagnostics": [], "message": ""},
    )
    assert main(["costs", "--history"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("channel/video:")
    assert "Tokens: 120" in output
