"""Shared pytest fixtures for the AVO test suite."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def avo_dir(repo_root: Path) -> Path:
    return repo_root / "src" / "avo"


@pytest.fixture(scope="session")
def helpers_dir(repo_root: Path) -> Path:
    """Compatibility shims under helpers/ (deprecated)."""
    return repo_root / "helpers"


@pytest.fixture(scope="session")
def iteration_proofing_fixture_dir(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "iteration-proofing"


@pytest.fixture(scope="session")
def iteration_proofing_manifest(
    iteration_proofing_fixture_dir: Path,
) -> dict[str, object]:
    return json.loads(
        (iteration_proofing_fixture_dir / "manifest.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def canonical_json_hash() -> Callable[[object], str]:
    from avo.timeline.contracts import content_hash

    return content_hash


@pytest.fixture
def footage_project_factory(tmp_path: Path):
    from avo.timeline.workspace import TimelineWorkspace

    def create(*, video_id: str = "fixture", provider: str = "example"):
        raw_dir = tmp_path / video_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        project = raw_dir / "avo.project.json"
        project.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "provider": provider,
                    "videoId": video_id,
                    "rawDir": str(raw_dir),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        workspace = TimelineWorkspace.from_project(project)
        workspace.initialize()
        return workspace

    return create
