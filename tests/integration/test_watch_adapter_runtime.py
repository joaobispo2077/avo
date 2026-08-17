from pathlib import Path

import pytest

from avo.adapters.base import JobRequest
from avo.adapters.understand.watch_skill import WatchSkillAdapter, _bundled_executable


def test_bundled_watch_skill_executable_contract():
    bundled = _bundled_executable()
    if not bundled:
        pytest.skip("watch-skill is not installed under tools/watch-skill")
    adapter = WatchSkillAdapter()
    result = adapter.run(
        JobRequest(
            job="understand",
            label="version",
            argv=["version"],
            root=Path(__file__).resolve().parents[2],
        )
    )
    if result.exit_code == 2 and str(result.stderr).startswith(
        "watch-skill unavailable"
    ):
        pytest.skip(result.stderr)
    assert result.exit_code == 0, result.stderr
    assert "tools/watch-skill" in adapter.executable.replace(chr(92), "/")
    parts = result.stdout.strip().split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)
