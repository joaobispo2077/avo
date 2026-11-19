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
            "avo.speech_dependencies._alignment_runtime_versions",
            return_value={"whisperx": "fixture"},
            create=True,
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


@pytest.mark.parametrize("changed", [False, True])
def test_initial_word_evidence_binds_models_across_actual_analysis(tmp_path, changed):
    from copy import deepcopy

    before = {
        "transcription": {"status": "observed", "files": {"asr.bin": "c" * 64}},
        "alignment": {"status": "observed", "files": {"align.bin": "d" * 64}},
    }
    after = deepcopy(before)
    if changed:
        after["alignment"]["files"]["align.bin"] = "e" * 64
    adapter = CuttingAnalysisAdapter(
        SimpleNamespace(project={}), SimpleNamespace(effective={})
    )
    adapter._model_bindings["en"] = {"model": "declared metadata fixture"}
    word = {
        "text": "word",
        "start": 0,
        "end": 0.2,
        "alignmentStatus": "aligned",
        "eligibleEdge": True,
    }
    with (
        mock.patch.object(adapter, "dependency_bindings", side_effect=[before, after]),
        mock.patch.object(adapter, "_transcriber"),
        mock.patch.object(adapter, "_alignment"),
        mock.patch(
            "avo.adapters.media.cutting_analysis.CuttingAcousticsAdapter"
        ) as acoustic,
    ):
        acoustic.return_value.analyze.return_value = {
            "alignment": {"words": [word], "chars": [], "bindings": {}},
            "waveform": {"frames": []},
            "speechRanges": [],
            "coverage": {"observed": True, "start": 0, "end": 1},
            "bindings": {},
            "candidates": [],
        }
        result = adapter.analyze(
            tmp_path / "source.wav",
            language="en",
            fingerprint={"sha256": "a" * 64},
            selection={},
            sync_ref={},
            source_range={},
        )
    if changed:
        assert result["status"] == "blocked"
        assert result["words"] == []
        assert any("changed" in issue for issue in result["uncertainty"])
    else:
        assert result["status"] == "pass"
        assert result["speechDependencies"] == before


@pytest.mark.parametrize("provider_missing", [False, True])
def test_word_dependency_settings_preserve_existing_scope_resolution(
    tmp_path, monkeypatch, provider_missing
):
    from avo import init_project, paths, speech_dependencies, video_context

    configured = {
        "cutting": {
            "language": "pt",
            "runtimeRefs": {"transcription": {"device": "cpu"}},
        }
    }
    provider = {
        "routingOverrides": {"cutting": {"language": "en", "guards": {"beforeMs": 200}}}
    }
    project = {
        "provider": "fixture",
        "cutting": {
            "language": "en",
            "runtimeRefs": {"transcription": {"device": "cuda"}},
        },
    }

    def load_provider(*args, **kwargs):
        if provider_missing:
            raise FileNotFoundError("No optional provider manifest")
        return provider

    monkeypatch.setattr(paths, "repo_root", lambda root=None: tmp_path)
    monkeypatch.setattr(video_context, "repo_root", lambda root=None: tmp_path)
    monkeypatch.setattr(init_project, "load_config", lambda root: configured)
    monkeypatch.setattr(video_context, "load_config", lambda root: configured)
    monkeypatch.setattr(init_project, "load_provider", load_provider)
    monkeypatch.setattr(video_context, "load_provider", load_provider)
    monkeypatch.setattr(
        speech_dependencies,
        "speech_dependency_bindings",
        lambda project, effective: effective,
    )
    context = video_context.VideoContext(
        provider="fixture",
        video_id="video",
        raw_dir=tmp_path,
        video_key=None,
        project=project,
    )
    expected = video_context.resolve_context_cutting_policy(context).effective
    actual = speech_dependencies.workspace_speech_dependencies(
        SimpleNamespace(project=project)
    )
    assert actual == expected
    assert actual["language"] == "en"
    assert actual["runtimeRefs"]["transcription"]["device"] == "cuda"


def test_alignment_package_updates_change_binding_without_loading_runtime(tmp_path):
    import sys

    from avo import speech_dependencies

    prefix = tmp_path / "isolated"
    python = prefix / "Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"same interpreter")
    packages = prefix / "Lib/site-packages"
    versions = {
        "whisperx": "3.8.6",
        "torch": "2.10.0",
        "torchaudio": "2.10.0",
        "transformers": "4.57.0",
        "numpy": "2.3.0",
        "nltk": "3.9.0",
    }
    for name, value in versions.items():
        directory = packages / (name + "-" + value + ".dist-info")
        directory.mkdir(parents=True)
        (directory / "METADATA").write_text(
            "Name: " + name + "\nVersion: " + value + "\n", encoding="utf-8"
        )
    punkt = prefix / "punkt"
    punkt.mkdir()
    (punkt / "table.tab").write_bytes(b"same tokenizer")
    weights = prefix / "alignment.bin"
    weights.write_bytes(b"same weights")
    runtime = {
        "python": str(python),
        "nltkData": str(punkt),
        "models": {
            "pt": {
                "path": str(prefix),
                "files": {"alignment.bin": source_fingerprint(weights)["sha256"]},
            }
        },
    }
    loaded = set(sys.modules)
    before = speech_dependencies._alignment_dependencies(runtime)
    (packages / "whisperx-3.8.6.dist-info/METADATA").write_text(
        "Name: whisperx\nVersion: 3.8.7\n", encoding="utf-8"
    )
    after = speech_dependencies._alignment_dependencies(runtime)
    assert before["status"] == after["status"] == "observed"
    assert before["versions"] == versions
    assert after["versions"]["whisperx"] == "3.8.7" and before != after
    assert before["files"] == after["files"]
    assert before["configured"] == after["configured"]
    runtime["device"] = "cuda"
    revised = speech_dependencies._alignment_dependencies(runtime)
    assert "device" not in before["configured"]
    assert revised["configured"]["device"] == "cuda"
    assert not (set(versions) & (set(sys.modules) - loaded))
