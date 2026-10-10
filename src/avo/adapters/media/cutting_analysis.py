"""Compose existing local ASR with routed acoustics and optional alignment."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Lock

from avo.adapters.media.cutting_acoustics import CuttingAcousticsAdapter
from avo.adapters.understand.cutting_alignment import CuttingAlignmentAdapter
from avo.model_sources import PreflightError, preflight, resolve_job
from avo.timeline.ports import ToolError
from avo.transcribe import MODEL_FILES, LocalTranscriber, source_fingerprint


def _dependency_files(paths):
    """Read current local bytes without provisioning or importing model runtimes."""
    files = {}
    for path in paths:
        path = Path(path)
        try:
            files[str(path.resolve())] = source_fingerprint(path)["sha256"]
        except OSError:
            files[str(path.resolve())] = None
    return {
        "status": "observed" if files and all(files.values()) else "unknown",
        "files": files,
    }


def _alignment_config_complete(runtime, punkt_files):
    models = runtime.get("models") or {}
    return bool(
        runtime.get("python")
        and punkt_files
        and models
        and all(model.get("path") and model.get("files") for model in models.values())
    )


def _alignment_dependencies(runtime):
    paths = []
    if runtime.get("python"):
        paths.append(Path(runtime["python"]))
    paths.extend(_configured_model_files(runtime.get("models") or {}))
    punkt = runtime.get("nltkData")
    punkt_files = (
        [path for path in Path(punkt).rglob("*") if path.is_file()] if punkt else []
    )
    paths.extend(punkt_files)
    result = {"configured": runtime, **_dependency_files(paths)}
    if not _alignment_config_complete(runtime, punkt_files):
        result["status"] = "unknown"
    return result


def _configured_model_files(models):
    paths = []
    for model in models.values():
        directory = Path(model.get("path") or ".")
        paths.extend(directory / name for name in (model.get("files") or {}))
    return paths


class CuttingAnalysisAdapter:
    def __init__(self, workspace, policy):
        self.workspace = workspace
        self.policy = policy
        self._transcribers = {}
        self._model_bindings = {}
        self._analysis_lock = Lock()

    def dependency_bindings(self):
        runtime = (self.policy.effective.get("runtimeRefs") or {}).get(
            "alignment"
        ) or {}
        try:
            resolved = resolve_job("transcribe", project=self.workspace.project)
            source = resolved.pin.get("source") or {}
            if not source.get("artifactPath"):
                raise ValueError("prepared local ASR artifact is unavailable")
            directory = Path(source["artifactPath"])
            transcription = {
                "model": resolved.id,
                "policyHash": resolved.policy_hash,
                **_dependency_files(directory / name for name in MODEL_FILES),
            }
        except (PreflightError, ToolError, OSError, RuntimeError, ValueError) as exc:
            transcription = {"status": "unknown", "reason": str(exc)}
        return {
            "transcription": transcription,
            "alignment": _alignment_dependencies(runtime),
        }

    def _transcriber(self, language):
        if language in self._transcribers:
            current = self.dependency_bindings()["transcription"]
            loaded = self._model_bindings[language]
            actual_files = {
                Path(name).name: digest
                for name, digest in current.get("files", {}).items()
            }
            expected = (
                loaded["model"],
                loaded["resolvedPolicyHash"],
                loaded["modelFiles"],
            )
            observed = (current.get("model"), current.get("policyHash"), actual_files)
            if current.get("status") != "observed" or expected != observed:
                raise ToolError(
                    "cutting-transcribe-stale",
                    "cached ASR model/policy/bytes changed; start a fresh adapter",
                )
            return self._transcribers[language]
        try:
            resolved = resolve_job("transcribe", project=self.workspace.project)
            source = resolved.pin.get("source") or {}
            model_path = source.get("artifactPath")
            if not model_path or source.get("kind") not in {None, "artifact", "cache"}:
                raise ToolError(
                    "cutting-transcribe-model",
                    "prepared local ASR artifact is required",
                )
            preflight(resolved)
            model_dir = Path(model_path)
            # Cutting's initial acoustic runtime stays on CPU, leaving visual VRAM independent.
            transcriber = LocalTranscriber(
                model=resolved.id,
                model_dir=model_dir,
                language=language,
                device="cpu",
                compute_type="int8",
                num_workers=1,
            )
            self._model_bindings[language] = {
                "engine": "faster-whisper",
                "version": transcriber.engine_version,
                "model": resolved.id,
                "device": "cpu",
                "computeType": "int8",
                "modelFiles": {
                    name: source_fingerprint(model_dir / name)["sha256"]
                    for name in MODEL_FILES
                },
                "resolvedPolicyHash": resolved.policy_hash,
            }
            self._transcribers[language] = transcriber
            return transcriber
        except (PreflightError, OSError, RuntimeError, ValueError) as exc:
            raise ToolError("cutting-transcribe-runtime", str(exc)) from exc

    def _alignment(self):
        runtime = (self.policy.effective.get("runtimeRefs") or {}).get(
            "alignment"
        ) or {}
        if (
            not runtime.get("python")
            or not runtime.get("models")
            or not runtime.get("nltkData")
        ):
            raise ToolError(
                "cutting-alignment-missing",
                "explicit optional alignment runtime/models/Punkt are required",
            )
        return CuttingAlignmentAdapter(
            Path(runtime["python"]),
            runtime["models"],
            nltk_data=Path(runtime["nltkData"]),
            timeout=runtime.get("timeoutSeconds", 120),
        )

    def analyze(self, source, **request):
        # One CPU model job at a time, even when callers share this adapter.
        with self._analysis_lock:
            return self._analyze(source, **request)

    def _analyze(self, source, **request):
        language = (
            request.get("language") or self.policy.effective.get("language") or "pt-BR"
        )
        payload = {
            "sourceRef": {
                "locator": str(source),
                "sha256": request["fingerprint"]["sha256"],
            },
            "routing": request.get("selection", {}),
            "syncRef": request.get("sync_ref", {}),
            "preprocessing": {"sourceRange": request.get("source_range")},
            "language": language,
            "status": "blocked",
            "words": [],
            "acousticRanges": [],
            "vad": [],
            "alignment": {"status": "missing", "characters": []},
            "tools": [],
            "measurements": {
                "analysisSeconds": None,
                "peakMemoryBytes": None,
                "peakVramBytes": None,
            },
            "coverage": {"observed": False},
            "uncertainty": [],
            "pauseCandidates": [],
        }
        if language.lower().split("-")[0] not in {"pt", "en"}:
            payload.update(
                status="unknown",
                alignment={"status": "unsupported", "characters": []},
                uncertainty=["cutting language has not been validated"],
            )
            return payload
        started = time.perf_counter()
        try:
            transcriber = self._transcriber(language)
            aligner = self._alignment()
            adapter = CuttingAcousticsAdapter(transcriber=transcriber, aligner=aligner)
            result = adapter.analyze(source, **request)
            alignment = result["alignment"]
            if not alignment:
                raise ToolError(
                    "cutting-alignment-empty", "no aligned speech was observed"
                )
            payload.update(
                status="pass",
                words=alignment["words"],
                acousticRanges=result["waveform"]["frames"],
                vad=result["speechRanges"],
                coverage=result["coverage"],
                alignment={"status": "pass", "characters": alignment["chars"]},
                tools=[
                    self._model_bindings[language],
                    alignment["bindings"],
                    result["bindings"],
                ],
                pauseCandidates=result["candidates"],
            )
            payload["measurements"]["analysisSeconds"] = time.perf_counter() - started
            payload["uncertainty"] = [
                "pause editorial function requires source-bound context evidence"
            ]
        except (ToolError, OSError, RuntimeError, ValueError) as exc:
            payload["uncertainty"] = [str(exc)]
        return payload
