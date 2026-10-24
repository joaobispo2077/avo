import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_actual_local_installer_copies_guidance_to_a_neutral_home(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    script = "const os=require('os');os.homedir=()=>process.argv[1];const i=require(process.argv[2]);if(!i.installSkillsFallback(process.argv[3],'codex',{dryRun:false}))process.exit(2);"
    result = subprocess.run(
        [node, "-e", script, str(tmp_path), str(ROOT / "bin/install.cjs"), str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    installed = tmp_path / ".codex/skills/avo-pipeline"
    gateway = (installed / "SKILL.md").read_text(encoding="utf8")
    assert "/avo.direction" in gateway and "/avo.briefstart" in gateway
    for name in ("trim", "media", "motion", "sound"):
        text = (installed / f"references/{name}.md").read_text(encoding="utf8")
        assert "briefing.stageContexts" in text
        assert "offered" in text
    assert (installed / "references/direction.md").is_file()
    assert (installed / "references/briefstart.md").is_file()


def test_engine_public_aliases_reach_the_real_shared_command_boundary(
    capsys, monkeypatch
):
    from avo.engine_cli import main

    monkeypatch.setattr("avo.direction_cli._active_provider", lambda: "")
    assert main(["direction", "catalog", "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert len(value["builtins"]) == 4
