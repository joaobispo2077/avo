"""Shared pytest fixtures for the AVO test suite."""

from __future__ import annotations

import sys
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
