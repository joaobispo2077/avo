"""Shared pytest fixtures for the AVO test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def helpers_dir(repo_root: Path) -> Path:
    return repo_root / "helpers"
