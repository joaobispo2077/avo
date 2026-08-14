"""Shared external-project and deterministic port fakes for timeline tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import pytest


@dataclass
class FakeClock:
    value: str = "2026-08-13T12:00:00Z"

    def now_iso(self) -> str:
        return self.value


@dataclass
class FakePort:
    result: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run(self, **request: Any) -> dict[str, Any]:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return dict(self.result)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def timeline_project(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "external-footage-project"
    (raw_dir / "edit" / "timeline").mkdir(parents=True)
    (raw_dir / "edit" / "review").mkdir(parents=True)
    (raw_dir / "edit" / "transcripts").mkdir(parents=True)
    (raw_dir / "raw-a.bin").write_bytes(b"raw-a")
    return raw_dir


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def candidate_file(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"candidate-v1")
    return candidate


@pytest.fixture
def fake_watch() -> FakePort:
    return FakePort({"status": "pass", "coverage": {"mode": "full"}, "findings": []})


@pytest.fixture
def fake_transcription() -> FakePort:
    return FakePort({"status": "pass", "language": "pt-BR", "words": []})
