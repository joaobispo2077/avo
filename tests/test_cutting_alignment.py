"""Alignment never provisions missing optional resources implicitly."""

import hashlib
import json
import subprocess
import sys
from unittest import mock

import pytest

from avo.adapters.understand.cutting_alignment import (
    CuttingAlignmentAdapter,
    normalize_alignment,
)
from avo.timeline.ports import ToolError


def test_missing_runtime_rejected_without_subprocess(tmp_path):
    adapter = CuttingAlignmentAdapter(tmp_path / "missing-python.exe", {})
    with mock.patch("subprocess.run") as run:
        with pytest.raises(ToolError, match="runtime"):
            adapter.align(tmp_path / "input.wav", language="pt-BR")
        run.assert_not_called()


def test_unsupported_language_cannot_claim_alignment(tmp_path):
    adapter = CuttingAlignmentAdapter(tmp_path / "missing", {})
    with pytest.raises(ToolError, match="language"):
        adapter.align(tmp_path / "input.wav", language="ja")


def test_wildcards_and_missing_character_times_are_not_edge_anchors():
    raw = {
        "segments": [
            {
                "words": [{"word": "2014", "start": 0, "end": 0.2}],
                "chars": [{"char": "2", "start": 0, "end": 0.05}],
            }
        ]
    }
    result = normalize_alignment(raw, dictionary={"a": 1}, source_start=3)
    assert result["words"][0]["eligibleEdge"] is False
    assert result["chars"][0]["eligibleEdge"] is False


def test_character_evidence_maps_back_to_source_clock():
    raw = {
        "segments": [
            {
                "words": [{"word": "a", "start": 0.1, "end": 0.2}],
                "chars": [{"char": "a", "start": 0.1, "end": 0.2, "score": 0.9}],
            }
        ]
    }
    result = normalize_alignment(raw, dictionary={"a": 1}, source_start=3)
    assert result["chars"][0]["start"] == 3.1
    assert result["chars"][0]["eligibleEdge"] is True


def test_word_times_without_characters_cannot_anchor_cuts():
    raw = {"segments": [{"words": [{"word": "a", "start": 0, "end": 0.1}]}]}
    assert (
        normalize_alignment(raw, dictionary={"a": 1})["words"][0]["eligibleEdge"]
        is False
    )


def test_offline_worker_environment_and_manifest_checked(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    digest = hashlib.sha256(b"{}").hexdigest()
    nltk = tmp_path / "nltk"
    (nltk / "tokenizers" / "punkt_tab" / "portuguese").mkdir(parents=True)
    adapter = CuttingAlignmentAdapter(
        sys.executable,
        {"pt": {"path": str(model), "files": {"config.json": digest}}},
        nltk_data=nltk,
    )
    response = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps({"raw": {"segments": []}, "dictionary": {}})
    )
    with mock.patch("subprocess.run", return_value=response) as run:
        assert adapter.align(tmp_path / "input.wav", language="pt-BR")["observed"]
    kwargs = run.call_args.kwargs
    assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == ""
    assert json.loads(kwargs["input"])["expectedVersion"] == "3.8.6"
    (model / "config.json").write_text("changed")
    with pytest.raises(ToolError, match="fingerprint"):
        adapter.align(tmp_path / "input.wav", language="pt-BR")


def test_missing_punkt_never_launches_worker(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    adapter = CuttingAlignmentAdapter(
        sys.executable,
        {
            "en": {
                "path": str(model),
                "files": {"config.json": hashlib.sha256(b"{}").hexdigest()},
            }
        },
    )
    with mock.patch("subprocess.run") as run:
        with pytest.raises(ToolError, match="Punkt"):
            adapter.align(tmp_path / "input.wav", language="en")
        run.assert_not_called()
