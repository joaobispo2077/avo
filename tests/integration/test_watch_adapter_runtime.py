from pathlib import Path

from avo.adapters.base import JobRequest
from avo.adapters.understand.watch_skill import WatchSkillAdapter


def test_bundled_watch_skill_executable_contract():
    adapter = WatchSkillAdapter()
    result = adapter.run(
        JobRequest(
            job="understand", label="version", argv=["version"],
            root=Path(__file__).resolve().parents[2],
        )
    )
    assert result.exit_code == 0, result.stderr
    assert "tools/watch-skill" in adapter.executable.replace(chr(92), "/")
    parts = result.stdout.strip().split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)
