"""Human-final adoption is explicit and never changes automated outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.delivery import DeliveryError
from test_delivery_adoption import adoption as adoption_fixture


@pytest.fixture
def adoption(tmp_path, monkeypatch):
    return adoption_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def human_adoption(tmp_path, monkeypatch):
    data = adoption_fixture.__wrapped__(tmp_path, monkeypatch)
    identity = data.review["candidate"]
    payload = {
        "authority": "human-final",
        "decision": "approved",
        "approvalId": "human-final-fixture",
        "candidateIdentityHash": identity["identityHash"],
        "candidateSha256": identity["sha256"],
        "candidateByteSize": identity["byteSize"],
        "dependencyLockSha256": data.review["dependencyLockSha256"],
        "dependencies": identity["dependencies"],
        "actor": {"type": "user", "id": "fixture-creator"},
        "automatedEvidence": [
            {"kind": "watch", "status": "interrupted"},
            {"kind": "regression", "status": "unresolved"},
        ],
    }
    payload["dispositionHash"] = content_hash(payload)
    disposition = tmp_path / "edit" / "review" / "human-final-disposition.json"
    disposition.write_text(json.dumps(payload), encoding="utf-8")
    calls = []

    def validate(
        workspace, path, *, candidate, fingerprint, materialization, dependencies
    ):
        calls.append(path)
        assert candidate == data.master
        assert fingerprint["sha256"] == payload["candidateSha256"]
        assert materialization == data.kwargs["materialization"]
        assert dependencies == payload["dependencies"]
        assert json.loads(Path(path).read_text(encoding="utf-8")) == payload
        return payload

    monkeypatch.setattr(
        "avo.timeline.approval_service.require_human_final_disposition",
        validate,
        raising=False,
    )
    monkeypatch.setattr(
        "avo.timeline.pipeline.TimelinePipeline.active_candidate_snapshot",
        lambda _self: pytest.fail("human adoption must not use an unrelated snapshot"),
    )
    data.kwargs["review_path"] = None
    data.kwargs["human_final_disposition_path"] = disposition
    data.disposition = disposition
    data.payload = payload
    data.calls = calls
    return data


def test_human_final_adoption_is_explicit_and_preserves_automated_truth(human_adoption):
    data = human_adoption
    before = {
        path: path.read_bytes()
        for path in [data.master, data.disposition, *data.sidecars.values()]
    }
    manifest = data.service.adopt_existing(**data.kwargs)
    assert manifest["state"] == "review-ready"
    assert manifest["review"]["kind"] == "human-final-disposition"
    assert manifest["review"]["state"] == "human-approved"
    assert manifest["review"]["state"] != "ai-passed"
    assert "candidateSnapshot" not in manifest
    assert (
        manifest["adoption"]["humanFinalDisposition"]["sha256"]
        == file_fingerprint(data.disposition)["sha256"]
    )
    delivered = data.service.approve(
        actor="fixture-creator", reason="explicit human final authority"
    )
    assert delivered["state"] == "delivered"
    assert delivered["review"]["state"] == "human-approved"
    assert data.payload["automatedEvidence"][0]["status"] == "interrupted"
    assert before == {path: path.read_bytes() for path in before}
    assert len(data.calls) >= 2


def test_human_final_adoption_is_idempotent(human_adoption):
    data = human_adoption
    data.service.adopt_existing(**data.kwargs)
    data.service.approve(actor="fixture-creator", reason="exact human final")
    before = data.service.manifest_path.read_bytes()
    repeated = data.service.adopt_existing(**data.kwargs)
    assert repeated["state"] == "delivered"
    assert data.service.manifest_path.read_bytes() == before


@pytest.mark.parametrize("damage", ["master", "transcript", "head", "materialization"])
def test_human_final_cannot_override_integrity_failures(human_adoption, damage):
    data = human_adoption
    if damage == "master":
        data.master.write_bytes(b"changed")
    elif damage == "transcript":
        path = data.sidecars["json"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["source"]["sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif damage == "head":
        data.heads["tracks"] = "0" * 64
    else:
        data.kwargs["materialization_path"].write_text("{}", encoding="utf-8")
    with pytest.raises(DeliveryError):
        data.service.adopt_existing(**data.kwargs)
    assert not data.service.manifest_path.exists()
    assert data.calls == []


def test_human_disposition_tamper_invalidates_delivery(human_adoption):
    data = human_adoption
    data.service.adopt_existing(**data.kwargs)
    data.disposition.write_text(
        data.disposition.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    with pytest.raises(DeliveryError, match="changed"):
        data.service.validate_current()


def test_human_final_does_not_silently_relax_default(adoption):
    adoption.review["state"] = "blocked"
    adoption.review_path.write_text(json.dumps(adoption.review), encoding="utf-8")
    with pytest.raises(DeliveryError, match="review"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_adoption_requires_either_strict_review_or_explicit_disposition(adoption):
    adoption.kwargs["review_path"] = None
    with pytest.raises(DeliveryError, match="review"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_human_disposition_cannot_be_combined_with_ignored_review(human_adoption):
    data = human_adoption
    data.kwargs["review_path"] = data.review_path
    with pytest.raises(DeliveryError, match="exclusive"):
        data.service.adopt_existing(**data.kwargs)
