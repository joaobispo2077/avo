from __future__ import annotations

import json
from fractions import Fraction

import pytest

from avo.timeline.contracts import ContractError, validate_document
from avo.timeline.lineage import LineageError, validate_cmap_snapshot
from avo.timeline.models import (
    ArtifactIdentity,
    AudioSample,
    Fingerprint,
    FrameRate,
    ProgramFrame,
    StructuredTimelineError,
    Timebase,
    TimelineDomain,
    TimeValue,
)
from avo.timeline.store import ArtifactStore, StoreError


def test_invalid_timebases_rejected():
    for num, den in ((0, 1), (1, 0), (-1, 1)):
        with pytest.raises(ValueError):
            Timebase(num, den)


def test_source_domain_requires_source_id():
    with pytest.raises(ValueError):
        TimeValue(0, Timebase(1, 1000), TimelineDomain.RAW_SOURCE)


def test_non_monotonic_ranges_rejected():
    snapshot = {
        "sources": [
            {
                "sourceId": "raw",
                "kind": "raw",
                "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1},
            }
        ],
        "segments": [
            {
                "segmentId": "s",
                "sourceId": "raw",
                "in": {
                    "ticks": 10,
                    "timebase": {"num": 1, "den": 1000},
                    "domain": "raw-source",
                    "sourceId": "raw",
                },
                "out": {
                    "ticks": 5,
                    "timebase": {"num": 1, "den": 1000},
                    "domain": "raw-source",
                    "sourceId": "raw",
                },
                "reason": "bad",
            }
        ],
    }
    with pytest.raises(LineageError):
        validate_cmap_snapshot(snapshot)


def test_revision_parent_cycle_cannot_be_created(tmp_path):
    store = ArtifactStore(tmp_path / "cmap.json")
    store.initialize(
        artifact_type="cmap",
        artifact_id="x",
        video_id="v",
        provider="bishop",
        timeline_domain="raw-source",
    )
    with pytest.raises(StoreError):
        store.append_revision(
            snapshot={},
            actor="a",
            reason="cycle",
            parent_revision_id="r0001",
            revision_id="r0001",
        )


def test_artifact_identity_is_exact_and_serializes_for_contracts():
    identity = ArtifactIdentity(
        artifact_type="proof-plan",
        artifact_id="proof-plan-0001",
        revision_id="proof-plan-r0001",
        content_sha256="a" * 64,
    )
    assert identity.to_dict() == {
        "artifactType": "proof-plan",
        "artifactId": "proof-plan-0001",
        "revisionId": "proof-plan-r0001",
        "contentSha256": "a" * 64,
    }
    with pytest.raises(ValueError):
        ArtifactIdentity("", "proof-plan-0001", "proof-plan-r0001", "a" * 64)
    with pytest.raises(ValueError):
        ArtifactIdentity("proof-plan", "proof-plan-0001", "", "a" * 64)
    with pytest.raises(ValueError):
        ArtifactIdentity("proof-plan", "proof-plan-0001", "r0001", "A" * 64)


def test_fingerprint_has_portable_identity_and_contract_shape():
    fingerprint = Fingerprint(
        sha256="b" * 64,
        size_bytes=42,
        media_signature={"codec": "h264"},
        locator="renamed-copy.mp4",
    )
    assert fingerprint.identity == ("b" * 64, 42)
    assert fingerprint.to_dict() == {
        "sha256": "b" * 64,
        "sizeBytes": 42,
        "mediaSignature": {"codec": "h264"},
        "locator": "renamed-copy.mp4",
    }
    with pytest.raises(ValueError):
        Fingerprint("b" * 64, -1)


def test_program_frames_and_audio_samples_use_exact_rational_time():
    rate = FrameRate(30000, 1001)
    frame = ProgramFrame(30000, rate)
    sample = AudioSample(48000, 48000)
    assert frame.seconds == Fraction(1001, 1)
    assert sample.seconds == Fraction(1, 1)
    assert frame.to_dict() == {
        "frame": 30000,
        "frameRate": {"num": 30000, "den": 1001},
    }
    assert sample.to_dict() == {"sample": 48000, "sampleRate": 48000}
    for value in (
        lambda: FrameRate(0, 1),
        lambda: ProgramFrame(-1, rate),
        lambda: AudioSample(-1, 48000),
        lambda: AudioSample(0, 0),
    ):
        with pytest.raises(ValueError):
            value()


def test_structured_timeline_error_validates_and_preserves_falsey_evidence():
    failure = StructuredTimelineError(
        code="PROOF_CAPABILITY_GAP",
        message="missing capability",
        remediation="register an adapter",
        artifact_ref="proof-plan-0001",
        expected=0,
        actual=False,
    )
    assert failure.to_dict()["expected"] == 0
    assert failure.to_dict()["actual"] is False
    assert "entityRef" not in failure.to_dict()
    for request in (
        {"code": "", "message": "message", "remediation": "fix"},
        {"code": "CODE", "message": "", "remediation": "fix"},
        {"code": "CODE", "message": "message", "remediation": ""},
    ):
        with pytest.raises(ValueError):
            StructuredTimelineError(**request)


def test_contract_validation_resolves_local_cross_file_refs(tmp_path):
    shared = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://avo.test/shared.json",
        "$defs": {"sha": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
    }
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://avo.test/document.json",
        "type": "object",
        "required": ["sha256"],
        "properties": {"sha256": {"$ref": "https://avo.test/shared.json#/$defs/sha"}},
    }
    (tmp_path / "shared.json").write_text(json.dumps(shared), encoding="utf-8")
    (tmp_path / "document.json").write_text(json.dumps(document), encoding="utf-8")
    assert validate_document({"sha256": "a" * 64}, "document.json", root=tmp_path) == {
        "sha256": "a" * 64
    }
    with pytest.raises(ContractError):
        validate_document({"sha256": "A" * 64}, "document.json", root=tmp_path)
