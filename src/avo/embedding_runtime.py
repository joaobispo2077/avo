"""Explicit optional embedding worker execution without adapter imports."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from avo.embedding_manifest import EmbeddingError, load_embedding_manifest


def run_embedding_worker(verified, action, *, modality=None, items=None, timeout=120):
    request = {
        "action": action,
        "manifest": verified["document"],
        "modelPath": str(verified["directory"]),
        "jointSpace": verified["jointSpace"],
        "device": verified["runtime"].get("device", "cpu"),
        "modality": modality,
        "items": items or [],
        "ffmpeg": str(verified["ffmpeg"]),
    }
    environment = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "PYTHONNOUSERSITE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    if request["device"] == "cpu":
        environment["CUDA_VISIBLE_DEVICES"] = ""
    worker = (
        Path(__file__).parent / "adapters" / "understand" / "clap_embeddings_worker.py"
    )
    try:
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            completed = subprocess.run(
                [str(verified["python"]), "-I", str(worker)],
                input=json.dumps(request, allow_nan=False).encode(),
                stdout=output,
                stderr=errors,
                timeout=timeout,
                env=environment,
                check=False,
            )
            if completed.returncode:
                errors.seek(0)
                detail = errors.read(1024).decode("utf-8", errors="replace")
                raise EmbeddingError(f"local embedding runtime unavailable: {detail}")
            output.seek(0)
            payload = output.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise EmbeddingError("embedding worker output exceeds its byte budget")
        result = json.loads(payload)
        if result.get("jointSpace") != verified["jointSpace"]:
            raise EmbeddingError("embedding worker joint-space identity mismatch")
        return result
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError) as exc:
        raise EmbeddingError(f"local embedding execution unavailable: {exc}") from exc


def preflight_embedding_job(resolved):
    verified = load_embedding_manifest(resolved)
    run_embedding_worker(verified, "probe")
    return verified["jointSpace"]
