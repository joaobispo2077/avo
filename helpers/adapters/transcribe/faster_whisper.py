"""Local transcribe via bundled helpers/transcribe.py (subprocess boundary)."""

from __future__ import annotations

import os
import subprocess
import sys

from helpers.adapters.base import JobAdapter, JobRequest, JobResult


def _argv_with_model(argv: list[str], model: str) -> list[str]:
    if not model:
        return argv
    if "--model" in argv:
        return argv
    return ["--model", model, *argv]


class FasterWhisperAdapter:
    routing_id = "faster-whisper"

    def run(self, request: JobRequest) -> JobResult:
        from helpers.models import format_active_model, load_catalog, resolve_option_id

        script = request.root / "helpers" / "transcribe.py"
        if not script.is_file():
            return JobResult(
                exit_code=1,
                stderr=f"missing bundled engine script: {script}",
            )
        model_id = resolve_option_id("transcribe", root=request.root, label=request.label)
        catalog = load_catalog(request.root)
        model_label = format_active_model(catalog, "transcribe", model_id)
        argv = _argv_with_model(request.argv, model_id)
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
        )
