"""Paid transcribe stub — ElevenLabs API wiring deferred to follow-up task."""

from __future__ import annotations

import os

from avo.adapters.base import JobAdapter, JobRequest, JobResult


class ElevenLabsAdapter:
    routing_id = "elevenlabs"

    def run(self, request: JobRequest) -> JobResult:
        from avo.models import format_active_model, load_catalog, resolve_option_id

        catalog = load_catalog(request.root)
        model_id = resolve_option_id("transcribe", root=request.root, label="paid")
        model_label = format_active_model(catalog, "transcribe_paid", model_id)
        key = request.env.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            return JobResult(
                exit_code=2,
                stderr=(
                    "ElevenLabs paid transcribe is not configured: set ELEVENLABS_API_KEY. "
                    "Full API adapter is planned; use --label local for faster-whisper."
                ),
                models_used={"transcribe": model_label},
            )
        return JobResult(
            exit_code=2,
            stderr=(
                "ElevenLabs adapter stub: API key present but paid transcribe is not "
                "implemented yet. Output will match helpers/transcribe.py JSON schema."
            ),
            models_used={"transcribe": model_label},
        )
