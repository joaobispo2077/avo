from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BUILDER_PATH = ROOT / "tests" / "fixtures" / "timeline" / "build_fixtures.py"
spec = importlib.util.spec_from_file_location("builder", BUILDER_PATH)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "avo.cli", *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(builder.shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_parameter_driven_sync_cli_reaches_sync_ready(tmp_path: Path) -> None:
    media = tmp_path / "media"
    builder.build_fixture_set(media)
    raw = tmp_path / "project"
    raw.mkdir()
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "provider": "bishop",
                "rawDir": str(raw),
                "timeline": {
                    "directory": "edit/timeline",
                    "reviewDirectory": "edit/review",
                    "generatedEdlPath": "edit/edl.json",
                },
            }
        ),
        encoding="utf-8",
    )
    init = run(
        "timeline", "init", "--project", str(project), "--video-id", "demo", "--json"
    )
    assert init.returncode == 0, init.stderr
    inventory = run(
        "sync",
        "inventory",
        "--project",
        str(project),
        "--video-id",
        "demo",
        "--source",
        str(media / "clean-clock.mp4"),
        "--source",
        str(media / "source-a.mp4"),
        "--json",
    )
    assert inventory.returncode == 0, inventory.stderr
    calibrate = run(
        "sync",
        "calibrate",
        "--project",
        str(project),
        "--video-id",
        "demo",
        "--kind",
        "constant-offset",
        "--picture",
        str(media / "clean-clock.mp4"),
        "--audio",
        str(media / "clean-clock.mp4"),
        "--offset-ms",
        "128",
        "--tolerance-ms",
        "20",
        "--sample",
        "0:-128",
        "--sample",
        "2000:1872",
        "--sample",
        "4000:3872",
        "--actor",
        "agent",
        "--reason",
        "calibrate",
        "--json",
    )
    assert calibrate.returncode == 0, calibrate.stderr
    validation = run(
        "sync", "validate", "--project", str(project), "--video-id", "demo", "--json"
    )
    assert validation.returncode == 0, validation.stderr
    evidence = json.loads(validation.stdout)
    assert evidence["status"] == "pass"
    decision = run(
        "sync",
        "decide",
        "--project",
        str(project),
        "--video-id",
        "demo",
        "--decision",
        "approved",
        "--candidate-sha256",
        "c" * 64,
        "--evidence-sha256",
        evidence["sha256"],
        "--actor",
        "creator",
        "--reason",
        "approved",
        "--json",
    )
    assert decision.returncode == 0, decision.stderr
    status = json.loads(
        run(
            "timeline",
            "status",
            "--project",
            str(project),
            "--video-id",
            "demo",
            "--json",
        ).stdout
    )
    assert status["pipeline"]["mainState"] == "sync-ready"
    assert status["artifacts"]["sync-map"]["approvedRevisionId"]
