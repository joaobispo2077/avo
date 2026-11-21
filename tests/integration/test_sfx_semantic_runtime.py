"""Explicit local CLAP qualification; no downloads or model load in ordinary CI."""

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tests.editing_craft_fixtures import channel_impulses
from tests.test_sfx_catalog import scan

from avo.adapters.media.sfx_analysis import SfxAnalyzer
from avo.adapters.understand.clap_embeddings import LocalClapEncoder
from avo.embedding_manifest import read_bounded_json
from avo.model_sources import ResolvedJob
from avo.sfx_catalog import SfxCatalogService
from avo.sfx_semantic import SemanticSoundRanker

PIN = os.environ.get("AVO_TEST_CLAP_PIN")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not PIN or not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="explicit AVO_TEST_CLAP_PIN and installed ffmpeg/ffprobe required",
    ),
]


def test_offline_clap_search_uses_real_joint_space_and_exact_source_cache(
    tmp_path, monkeypatch, record_property
):
    pin = read_bounded_json(Path(PIN))
    encoder = LocalClapEncoder(
        ResolvedJob("audio_embed", pin["id"], deepcopy(pin), {}, "qualification"),
        ResolvedJob("text_embed", pin["id"], deepcopy(pin), {}, "qualification"),
        timeout=240,
    )
    identity = encoder.preflight()
    assert identity["dimension"] == 512 and identity["normalization"] == "l2"
    record_property("jointSpace", json.dumps(identity, sort_keys=True))
    record_property("manifestSha256", pin["source"]["manifestSha256"])
    calls = []
    actual_encode = encoder.encode

    def observed(modality, items):
        calls.append(modality)
        result = actual_encode(modality, items)
        vectors = np.asarray(result["vectors"])
        assert result["jointSpace"] == identity
        assert vectors.shape == (len(items), identity["dimension"])
        assert np.isfinite(vectors).all()
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
        return result

    monkeypatch.setattr(encoder, "encode", observed)
    library = tmp_path / "sounds"
    library.mkdir()
    source = channel_impulses(library / "impact.wav")
    workspace = SimpleNamespace(raw_dir=tmp_path / "project")
    ranker = SemanticSoundRanker(workspace, roots={"fixture": library}, encoder=encoder)
    service = SfxCatalogService(
        workspace, roots={"fixture": library}, analyzer=SfxAnalyzer(), semantic=ranker
    )
    generation = scan(service)
    before = deepcopy(generation)
    first = service.search("a short percussive impact", mode="semantic", limit=1)
    assert first["status"] == "ok", first
    assert first["results"][0]["entryId"] == generation["entries"][0]["entryId"]
    assert calls == ["text", "audio"]
    second = service.search("a short percussive impact", mode="semantic", limit=1)
    assert second["results"] == first["results"]
    assert calls == ["text", "audio", "text"]
    cache = next((workspace.raw_dir / "edit/sfx/embeddings").glob("*.json"))
    record = read_bounded_json(cache)
    assert record["binding"]["generationId"] == generation["generationId"]
    assert (
        record["binding"]["sourceSha256"]
        == generation["entries"][0]["source"]["sha256"]
    )
    assert service.show() == before
    assert not (workspace.raw_dir / "edit/timeline").exists()
    # Changed bytes cannot reuse an embedding even if the catalogue was not refreshed.
    with source.open("ab") as handle:
        handle.write(b"changed-source")
    changed = service.search("a short percussive impact", mode="semantic", limit=1)
    assert changed["status"] == "unavailable" and changed["results"] == []
    assert any("digest changed" in warning for warning in changed["warnings"])
