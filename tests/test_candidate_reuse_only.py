from __future__ import annotations

import json

import pytest

from avo.adapters.transcribe.candidate import CandidateTranscriptionAdapter
from avo.timeline.contracts import file_fingerprint
from avo.timeline.ports import ToolError


@pytest.mark.parametrize("case", ["missing", "stale", "other-model", "malformed"])
def test_reuse_only_never_starts_asr(tmp_path, monkeypatch, case):
    candidate = tmp_path / "master.mp4"
    candidate.write_bytes(b"unchanged master")
    edit = tmp_path / "edit"
    transcript = edit / "transcripts" / "master.json"
    transcript.parent.mkdir(parents=True)
    payload = {
        "source": {"sha256": file_fingerprint(candidate)["sha256"]},
        "model": "large-v3",
        "words": [],
        "text": "fala",
    }
    if case == "stale":
        payload["source"]["sha256"] = "0" * 64
    if case == "other-model":
        payload["model"] = "small"
    if case != "missing":
        transcript.write_text(
            "[invalid" if case == "malformed" else json.dumps(payload), encoding="utf-8"
        )

    def forbidden(*args, **kwargs):
        pytest.fail("reuse-only started ASR")

    monkeypatch.setattr("avo.transcribe.transcribe_one", forbidden)
    adapter = CandidateTranscriptionAdapter(
        runtime=forbidden, model="large-v3", reuse_only=True
    )
    with pytest.raises(ToolError) as error:
        adapter.transcribe(candidate, edit_dir=edit)
    assert error.value.code == "TRANSCRIPT_REUSE_UNAVAILABLE"
    assert error.value.retryable is False


def test_reuse_only_analyzes_existing_exact_transcript(tmp_path, monkeypatch):
    candidate = tmp_path / "master.mp4"
    candidate.write_bytes(b"unchanged master")
    edit = tmp_path / "edit"
    transcript = edit / "transcripts" / "master.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "source": {"sha256": file_fingerprint(candidate)["sha256"]},
                "model": "large-v3",
                "words": [],
                "text": "fala existente",
            }
        ),
        encoding="utf-8",
    )

    def forbidden(*args, **kwargs):
        pytest.fail("reuse-only started ASR")

    monkeypatch.setattr("avo.transcribe.transcribe_one", forbidden)
    result = CandidateTranscriptionAdapter(
        runtime=forbidden, model="large-v3", reuse_only=True
    ).transcribe(candidate, edit_dir=edit, terms=["ausente"])
    assert result["transcriptPath"] == str(transcript)
    assert result["findings"][0]["id"] == "missing-term-ausente"
