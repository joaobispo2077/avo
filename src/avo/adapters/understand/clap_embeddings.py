"""Explicitly provisioned local CLAP, isolated from the core Python environment."""

from __future__ import annotations

from avo.embedding_manifest import EmbeddingError, load_embedding_manifest
from avo.embedding_runtime import run_embedding_worker


class LocalClapEncoder:
    """A paired audio/text encoder; constructing it performs no I/O or model load."""

    def __init__(self, audio_job, text_job, *, timeout=120):
        self.audio_job = audio_job
        self.text_job = text_job
        self.timeout = timeout

    def _pair(self):
        if self.audio_job.job != "audio_embed" or self.text_job.job != "text_embed":
            raise EmbeddingError(
                "explicit audio_embed and text_embed jobs are required"
            )
        audio = load_embedding_manifest(self.audio_job)
        text = load_embedding_manifest(self.text_job)
        if audio["jointSpace"] != text["jointSpace"]:
            raise EmbeddingError("audio/text jobs use incompatible joint spaces")
        return audio

    def preflight(self):
        verified = self._pair()
        run_embedding_worker(verified, "probe", timeout=self.timeout)
        return verified["jointSpace"]

    def encode(self, modality, items):
        if modality not in {"audio", "text"} or not 1 <= len(items) <= 16:
            raise EmbeddingError("embedding request needs 1..16 audio or text items")
        verified = self._pair()
        result = run_embedding_worker(
            verified, "encode", modality=modality, items=items, timeout=self.timeout
        )
        # Verify artifacts again so a changed model/runtime cannot publish old identity.
        if self._pair()["jointSpace"] != verified["jointSpace"]:
            raise EmbeddingError("embedding artifacts changed during execution")
        return result
