"""CI transcribe stub: writes JSON, never loads faster_whisper / network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "engine" / "stub.wav"


def test_stub_writes_json_without_whisper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVO_CI_TRANSCRIBE_STUB", "1")

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("LocalTranscriber must not load")

    monkeypatch.setattr("avo.transcribe.LocalTranscriber", boom)
    from avo.engine_cli import main

    code = main(["transcribe", str(FIXTURE), "--edit-dir", str(tmp_path)])
    assert code in (0, None)
    out = tmp_path / "transcripts" / "stub.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["language_code"] == "pt-BR"
    assert len(payload["source"]["sha256"]) == 64


def test_avo_ci_does_not_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVO_CI", "1")
    monkeypatch.delenv("AVO_CI_TRANSCRIBE_STUB", raising=False)
    hits: list[bool] = []

    def boom(*_a: object, **_k: object) -> None:
        hits.append(True)
        raise RuntimeError("local PT-BR model is not prepared at ci-sentinel")

    monkeypatch.setattr("avo.transcribe.LocalTranscriber", boom)
    from avo.transcribe import transcribe_one

    with pytest.raises(RuntimeError, match="ci-sentinel"):
        transcribe_one(FIXTURE, tmp_path)
    assert hits
    assert not (tmp_path / "transcripts" / "stub.json").exists()
