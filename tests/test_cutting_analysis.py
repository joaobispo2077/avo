"""Missing optional capabilities stay visible in persisted source evidence."""

from types import SimpleNamespace
from unittest import mock

import pytest

from avo.adapters.media.cutting_analysis import CuttingAnalysisAdapter
from avo.timeline.ports import ToolError


def test_missing_alignment_runtime_returns_blocked_evidence(tmp_path):
    workspace = SimpleNamespace(project={}, timeline_dir=tmp_path)
    policy = SimpleNamespace(effective={"runtimeRefs": {}})
    adapter = CuttingAnalysisAdapter(workspace, policy)
    with mock.patch.object(
        adapter, "_transcriber", side_effect=ToolError("missing", "no model")
    ):
        result = adapter.analyze(
            tmp_path / "original.wav",
            selection={},
            source_range={},
            fingerprint={"sha256": "a" * 64},
            sync_ref={"locator": "sync.json", "sha256": "b" * 64},
            output_dir=tmp_path / "output",
            language="pt-BR",
        )
    assert result["status"] == "blocked"
    assert result["measurements"]["analysisSeconds"] is None
    assert result["coverage"]["observed"] is False
    assert result["pauseCandidates"] == []


def test_unsupported_language_never_starts_analysis(tmp_path):
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}, timeline_dir=tmp_path),
        SimpleNamespace(effective={"runtimeRefs": {}}),
    )
    with mock.patch.object(adapter, "_transcriber") as transcriber:
        result = adapter.analyze(
            tmp_path / "source.wav",
            language="ja",
            fingerprint={"sha256": "a" * 64},
            selection={},
            sync_ref={},
        )
    assert result["status"] == "unknown"
    assert result["alignment"]["status"] == "unsupported"
    transcriber.assert_not_called()


def test_no_aligned_speech_reports_blocked_instead_of_crashing(tmp_path):
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}, timeline_dir=tmp_path),
        SimpleNamespace(effective={"runtimeRefs": {}}),
    )
    with (
        mock.patch.object(adapter, "_transcriber"),
        mock.patch.object(adapter, "_alignment"),
        mock.patch(
            "avo.adapters.media.cutting_analysis.CuttingAcousticsAdapter"
        ) as acoustic,
    ):
        acoustic.return_value.analyze.return_value = {"alignment": None}
        result = adapter.analyze(
            tmp_path / "silent.wav", fingerprint={"sha256": "a" * 64}
        )
    assert result["status"] == "blocked"
    assert result["measurements"]["analysisSeconds"] is None
    assert result["coverage"]["observed"] is False
    assert "no aligned speech" in result["uncertainty"][0]


def test_aligned_words_are_persisted_for_physical_preview_edges(tmp_path):
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}, timeline_dir=tmp_path),
        SimpleNamespace(effective={"runtimeRefs": {}}),
    )
    adapter._model_bindings["pt-BR"] = {"engine": "injected-fixture"}
    observed = [{"text": "unit", "start": 0.2, "end": 0.4, "eligibleEdge": True}]
    with (
        mock.patch.object(adapter, "_transcriber"),
        mock.patch.object(adapter, "_alignment"),
        mock.patch(
            "avo.adapters.media.cutting_analysis.CuttingAcousticsAdapter"
        ) as acoustic,
    ):
        acoustic.return_value.analyze.return_value = {
            "alignment": {"words": observed, "chars": [], "bindings": {}},
            "words": [{"text": "unit", "start": 0.1, "end": 0.3}],
            "waveform": {"frames": []},
            "speechRanges": [],
            "coverage": {"observed": True},
            "bindings": {},
            "candidates": [],
        }
        result = adapter.analyze(
            tmp_path / "original.wav", fingerprint={"sha256": "a" * 64}
        )
    assert result["status"] == "pass"
    assert result["words"] == observed


def test_dependency_bindings_change_with_local_model_and_punkt_bytes(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.bin").write_bytes(b"first")
    python = tmp_path / "python.exe"
    python.write_bytes(b"interpreter")
    punkt = tmp_path / "punkt"
    punkt.mkdir()
    (punkt / "table.tab").write_bytes(b"tokens")
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}),
        SimpleNamespace(
            effective={
                "runtimeRefs": {
                    "alignment": {
                        "python": str(python),
                        "nltkData": str(punkt),
                        "models": {
                            "pt": {
                                "path": str(model),
                                "files": {"weights.bin": "a" * 64},
                            }
                        },
                    }
                }
            }
        ),
    )
    with mock.patch(
        "avo.adapters.media.cutting_analysis.resolve_job",
        side_effect=ValueError("missing local ASR"),
    ):
        first = adapter.dependency_bindings()
        (model / "weights.bin").write_bytes(b"second")
        second = adapter.dependency_bindings()
        (punkt / "table.tab").write_bytes(b"changed")
        third = adapter.dependency_bindings()
    assert first != second != third
    assert first["transcription"]["status"] == "unknown"


def test_cached_transcriber_refuses_changed_managed_model_bytes(tmp_path):
    from avo.transcribe import MODEL_FILES, source_fingerprint

    model = tmp_path / "asr"
    model.mkdir()
    for name in MODEL_FILES:
        (model / name).write_bytes(b"original-model")
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}), SimpleNamespace(effective={})
    )
    adapter._transcribers["en"] = object()
    adapter._model_bindings["en"] = {
        "model": "local",
        "resolvedPolicyHash": "b" * 64,
        "modelFiles": {
            name: source_fingerprint(model / name)["sha256"] for name in MODEL_FILES
        },
    }
    resolved = SimpleNamespace(
        id="local", policy_hash="b" * 64, pin={"source": {"artifactPath": str(model)}}
    )
    with mock.patch(
        "avo.adapters.media.cutting_analysis.resolve_job", return_value=resolved
    ):
        assert adapter._transcriber("en") is adapter._transcribers["en"]
        (model / MODEL_FILES[0]).write_bytes(b"changed-model")
        with pytest.raises(ToolError, match="cached ASR"):
            adapter._transcriber("en")
