from __future__ import annotations

import pytest

from avo.timeline.store import ArtifactStore, StoreError

SHA="a"*64


def store_with_revision(tmp_path):
    store=ArtifactStore(tmp_path/"timeline"/"cmap.json")
    store.initialize(artifact_type="cmap",artifact_id="video:cmap",video_id="video",provider="bishop",timeline_domain="raw-source")
    revision=store.append_revision(snapshot={"sources":[],"segments":[]},actor="codex",reason="initial",created_at="2026-08-13T12:00:00Z")
    return store,revision


def test_exact_decision_is_immutable_and_effective(tmp_path) -> None:
    store,rev=store_with_revision(tmp_path)
    decision=store.record_decision(
        decision="approved",revision_id=rev["revisionId"],revision_hash=rev["contentHash"],
        candidate_hash=SHA,dependency_hashes={"cmap":rev["contentHash"]},actor="creator",
        checkpoint="cut-proof",scope="full-cut",reason="approved",evidence_bundle_hash=SHA,
        decided_at="2026-08-13T12:01:00Z",
    )
    assert decision["type"]=="approved"
    assert store.load()["approvedRevisionId"]==rev["revisionId"]
    assert store.effective_approval()["eventId"]==decision["eventId"]
    assert (tmp_path/"timeline"/"events"/"video-cmap"/(decision["eventId"]+".json")).is_file()


def test_decision_requires_exact_actor_candidate_dependencies_scope_and_evidence(tmp_path) -> None:
    store,rev=store_with_revision(tmp_path)
    base=dict(decision="approved",revision_id=rev["revisionId"],revision_hash=rev["contentHash"],candidate_hash=SHA,dependency_hashes={"cmap":rev["contentHash"]},actor="creator",checkpoint="cut-proof",scope="full",reason="ok",evidence_bundle_hash=SHA)
    for field in ("candidate_hash","dependency_hashes","actor","scope","evidence_bundle_hash"):
        value=dict(base); value[field]="" if field!="dependency_hashes" else {}
        with pytest.raises(StoreError): store.record_decision(**value)
