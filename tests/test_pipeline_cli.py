from __future__ import annotations

import json
from pathlib import Path

from avo.cli import main


def project(tmp_path: Path) -> Path:
    path = tmp_path / "avo.project.json"
    path.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "provider": "bishop",
        "videoId": "cli-pipeline",
        "rawDir": str(tmp_path),
    }), encoding="utf-8")
    return path


def test_pipeline_cli_init_status_stage_and_registry(tmp_path: Path, capsys):
    path = project(tmp_path)
    assert main(["pipeline", "run", "--project", str(path)]) == 0
    capsys.readouterr()
    assert main(["pipeline", "status", "--project", str(path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["pipeline"]["mainState"] == "intake"

    payload = tmp_path / "sources.json"
    payload.write_text(json.dumps({
        "rawInventory": {
            "sources": [{"sourceId": "raw-one", "sha256": "a" * 64}],
        }
    }), encoding="utf-8")
    assert main([
        "pipeline", "stage", "--project", str(path),
        "--stage", "sources-ready", "--payload", str(payload),
    ]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert staged["mainState"] == "sources-ready"

    assert main(["pipeline", "verify-commands", "--project", str(path)]) == 0
    registry = json.loads(capsys.readouterr().out)
    assert len(registry["commands"]) == 51
