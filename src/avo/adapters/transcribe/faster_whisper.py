"""Local transcribe via bundled helpers/transcribe.py (subprocess boundary)."""

from __future__ import annotations

import os
import subprocess
import sys

from avo.adapters.base import JobRequest, JobResult


def _argv_with_option(argv: list[str], flag: str, value: str | None) -> list[str]:
    if not value or flag in argv:
        return argv
    return [flag, value, *argv]


def _argv_with_model(argv: list[str], model: str) -> list[str]:
    return _argv_with_option(argv, "--model", model)


class FasterWhisperAdapter:
    routing_id = "faster-whisper"

    def run(self, request: JobRequest) -> JobResult:
        from avo.model_sources import (
            PreflightError,
            disclosure_for,
            preflight,
            resolve_job,
        )
        from avo.models import format_active_model, load_catalog

        script = request.root / "helpers" / "transcribe.py"
        if not script.is_file():
            return JobResult(
                exit_code=1,
                stderr=f"missing bundled engine script: {script}",
            )
        resolved = resolve_job("transcribe", root=request.root, label=request.label)
        try:
            preflight(resolved)
        except PreflightError as exc:
            return JobResult(
                exit_code=1,
                stderr=f"{exc.code}: {exc}",
                models_used={"transcribe": resolved.catalog_label or resolved.id},
                model_sources={"transcribe": disclosure_for(resolved)},
            )
        catalog = load_catalog(request.root)
        model_label = format_active_model(catalog, resolved.job_key, resolved.id)
        source = (
            resolved.pin.get("source")
            if isinstance(resolved.pin.get("source"), dict)
            else {}
        )
        runtime = (
            resolved.pin.get("runtime")
            if isinstance(resolved.pin.get("runtime"), dict)
            else {}
        )
        argv = _argv_with_model(request.argv, resolved.id)
        argv = _argv_with_option(argv, "--model-dir", source.get("artifactPath"))
        argv = _argv_with_option(argv, "--device", runtime.get("device"))
        argv = _argv_with_option(argv, "--compute-type", runtime.get("computeType"))
        argv = _argv_with_option(
            argv, "--language", request.env.get("AVO_TRANSCRIBE_LANGUAGE")
        )
        cmd = [sys.executable, str(script), *argv]
        env = {**os.environ, **request.env}
        proc = subprocess.run(
            cmd,
            cwd=str(request.root),
            env=env,
            capture_output=True,
            text=True,
        )
        return JobResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            models_used={"transcribe": model_label},
            model_sources={"transcribe": disclosure_for(resolved)},
        )
