from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent / "fixtures" / "timeline" / "build_fixtures.py"
SPEC = importlib.util.spec_from_file_location("timeline_fixture_builder", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_fixture_contracts_are_machine_readable() -> None:
    fixture_dir = MODULE_PATH.parent
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    legacy = json.loads(
        (fixture_dir / "legacy-edl-parity.json").read_text(encoding="utf-8")
    )
    assert manifest["fixtures"]["constant-plus-128ms"]["transform"]["offsetMs"] == 128
    assert manifest["fixtures"]["multi-source-reorder"]["expectedDurationMs"] == 3000
    assert legacy["approval"]["status"] == "unknown"
    assert "music" in legacy and "overlays" in legacy and "sound_effects" in legacy


@pytest.mark.skipif(MODULE.shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_generated_fixture_hashes_are_repeatable(tmp_path: Path) -> None:
    first = MODULE.build_fixture_set(tmp_path / "first")
    second = MODULE.build_fixture_set(tmp_path / "second")
    assert first == second
