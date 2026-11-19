"""Current speech identities remain inspectable without loading model runtimes."""

from types import SimpleNamespace
from unittest import mock

import pytest

from avo.adapters.media.cutting_analysis import CuttingAnalysisAdapter
from avo.transcribe import MODEL_FILES, source_fingerprint


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_dependency_metadata_keeps_both_configured_speech_jobs(tmp_path, device):
    model = tmp_path / "model"
    model.mkdir()
    for name in MODEL_FILES:
        (model / name).write_bytes(name.encode())
    python = tmp_path / "python.exe"
    python.write_bytes(b"declared isolated interpreter")
    punkt = tmp_path / "punkt"
    punkt.mkdir()
    (punkt / "table.tab").write_bytes(b"prepared tokenizer")
    weights = model / "alignment.bin"
    weights.write_bytes(b"declared alignment model")
    effective = {
        "runtimeRefs": {
            "transcription": {"device": device, "computeType": "float32"},
            "alignment": {
                "python": str(python),
                "nltkData": str(punkt),
                "models": {
                    "pt": {
                        "path": str(model),
                        "files": {
                            "alignment.bin": source_fingerprint(weights)["sha256"]
                        },
                    }
                },
            },
        }
    }
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}), SimpleNamespace(effective=effective)
    )
    resolved = SimpleNamespace(
        id="local", policy_hash="a" * 64, pin={"source": {"artifactPath": str(model)}}
    )
    with (
        mock.patch(
            "avo.adapters.media.cutting_analysis.resolve_job", return_value=resolved
        ),
        mock.patch(
            "avo.adapters.media.cutting_analysis.LocalTranscriber"
        ) as transcriber,
        mock.patch(
            "avo.adapters.media.cutting_analysis.CuttingAlignmentAdapter"
        ) as aligner,
    ):
        first = adapter.dependency_bindings()
        (model / MODEL_FILES[0]).write_bytes(b"changed ASR model")
        second = adapter.dependency_bindings()
    transcriber.assert_not_called()
    aligner.assert_not_called()
    assert first["transcription"]["status"] == "observed"
    assert first["alignment"]["status"] == "observed"
    assert first["transcription"]["runtime"] == {
        "device": device,
        "computeType": "float32",
    }
    assert first["transcription"]["model"] == "local"
    assert first["transcription"]["policyHash"] == "a" * 64
    assert first["transcription"] != second["transcription"]
    assert first["alignment"] == second["alignment"]


def test_shared_dependency_reader_changes_invalidate_cutting_and_recovery(monkeypatch):
    from pathlib import Path

    from avo.timeline import cutting_service, preparation_recovery

    cutting = object.__new__(cutting_service.CuttingService)
    cutting.analysis_port = None
    cutting.workspace = SimpleNamespace(project={})
    helper = (
        Path(cutting_service.__file__).resolve().parents[1] / "speech_dependencies.py"
    )
    original = preparation_recovery.file_fingerprint

    def changed(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return {**result, "sha256": "f" * 64} if Path(path) == helper else result

    with mock.patch.object(cutting, "_preparation_identity", return_value=None):
        before_cutting = cutting._implementation_binding()
        before_recovery = preparation_recovery._execution_hash()
        monkeypatch.setattr(cutting_service, "file_fingerprint", changed)
        monkeypatch.setattr(preparation_recovery, "file_fingerprint", changed)
        assert cutting._implementation_binding() != before_cutting
        assert preparation_recovery._execution_hash() != before_recovery
