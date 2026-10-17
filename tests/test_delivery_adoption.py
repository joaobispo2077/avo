"""Existing-master adoption must reuse exact evidence without media mutations."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.timeline.contracts import content_hash, dependency_lock_hash, file_fingerprint
from avo.timeline.delivery import DeliveryError, DeliveryService
from avo.timeline.review import CHECKPOINT_POLICIES, candidate_identity


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def adoption(tmp_path, monkeypatch):
    master = tmp_path / "edit" / "proofs" / "approved-master.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"exact-approved-master")
    heads = {
        name: str(index) * 64
        for index, name in enumerate(
            ("cmap", "sync-map", "bmap", "tracks", "animation"), 1
        )
    }
    body = {
        "kind": "assembly",
        "materializationId": "assembly-fixture",
        "output": file_fingerprint(master),
        "canonicalInputLock": dict(heads),
        "proofPlanHash": "a" * 64,
        "deliveryFidelityPolicyHash": "b" * 64,
        "pictureLineageHash": "c" * 64,
    }
    materialization = {**body, "materializationHash": content_hash(body)}
    materialization_path = _write(
        tmp_path / "edit" / "timeline" / "assembly.json", materialization
    )
    dependencies = {
        **heads,
        "proof-plan": materialization["proofPlanHash"],
        "materialization": materialization["materializationHash"],
        "delivery-fidelity-policy": materialization["deliveryFidelityPolicyHash"],
        "picture-lineage": materialization["pictureLineageHash"],
        "assembly-output": materialization["output"]["sha256"],
    }
    sidecars = {}
    transcript = {
        "schema_version": 1,
        "text": "fala final",
        "language_code": "pt-BR",
        "engine_language": "pt",
        "engine": "fixture",
        "engine_version": "1.0",
        "model": "fixture-ptbr",
        "source": {
            "sha256": materialization["output"]["sha256"],
            "size_bytes": master.stat().st_size,
            "path": str(master),
        },
        "words": [
            {
                "text": "fala",
                "start": 0,
                "end": 0.4,
                "type": "word",
                "speaker_id": None,
                "probability": 1,
            }
        ],
    }
    for extension in ("json", "txt", "md", "srt"):
        path = tmp_path / "edit" / "transcripts" / f"{master.stem}.{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(transcript) if extension == "json" else "fala\n",
            encoding="utf-8",
        )
        sidecars[extension] = path
    identity = candidate_identity(master, dependencies, "master")
    evidence = []
    for kind in sorted(CHECKPOINT_POLICIES["deliver"]["required"]):
        evidence.append(
            {
                "evidenceId": kind,
                "kind": kind,
                "tool": {"name": "fixture", "version": "1"},
                "runAt": "2026-10-14T12:00:00Z",
                "candidateHash": identity["sha256"],
                "candidateIdentityHash": identity["identityHash"],
                "dependencyLockSha256": dependency_lock_hash(dependencies),
                "dependencyHashes": dependencies,
                "dependencyProfile": "exact-candidate",
                "scope": {"mode": "full", "windows": [], "rationale": "fixture only"},
                "coverage": {"requiredWindows": 1, "reviewedWindows": 1},
                "status": "pass",
                "findings": [],
                "artifacts": [],
                "attempt": 1,
            }
        )
    review = {
        "schemaVersion": "1.0.0",
        "checkpoint": "deliver",
        "candidate": identity,
        "dependencyLockSha256": dependency_lock_hash(dependencies),
        "state": "ai-passed",
        "evidence": evidence,
        "attempts": [],
        "unresolvedRisks": [],
        "approval": None,
    }
    vision_path = _write(
        tmp_path / "edit" / "review" / "vision.json", {"fixture": "complete"}
    )
    watch = next(item for item in evidence if item["kind"] == "watch")
    watch["coverage"].update(
        requestedFrames=[0, 30], decodedFrames=[0, 30], observedFrames=[0, 30]
    )
    watch["policy"] = {"reviewContractHash": "e" * 64}
    watch["visionCoverageManifest"] = {
        "planHash": "f" * 64,
        "reviewContractHash": "e" * 64,
        "aggregateStatus": "pass",
        "artifact": {
            "path": str(vision_path),
            "sha256": file_fingerprint(vision_path)["sha256"],
        },
    }
    review_path = _write(
        tmp_path / "edit" / "review" / "deliver" / "review.json", review
    )
    snapshot = {
        "snapshotId": "candidate-snapshot-0001",
        "snapshotHash": "d" * 64,
        "candidate": materialization["output"],
        "state": "approved",
        "materialization": {
            "artifactId": "assembly-fixture",
            "sha256": materialization["materializationHash"],
        },
        "proofPlan": {
            "artifactId": "proof-plan-fixture",
            "sha256": materialization["proofPlanHash"],
        },
        "transcript": file_fingerprint(sidecars["json"]),
        "review": {"artifactId": "pre-master-review", "sha256": "e" * 64},
        "regressionResult": {"artifactId": "regression-fixture", "sha256": "f" * 64},
        "approval": {"artifactId": "approval-fixture", "sha256": "a" * 64},
    }
    pipeline_path = _write(tmp_path / "edit" / "timeline" / "pipeline-run.json", {})
    workspace = SimpleNamespace(
        raw_dir=tmp_path,
        pipeline_run_path=pipeline_path,
        active_dependency_snapshot=lambda: heads,
        require_active=lambda name: {"activeState": "valid"},
        notify_editlog=lambda: {"fixture": True},
    )
    monkeypatch.setattr(
        "avo.timeline.pipeline.TimelinePipeline.active_candidate_snapshot",
        lambda _self: snapshot,
    )
    monkeypatch.setattr(
        "avo.timeline.pipeline.TimelinePipeline.__init__",
        lambda _self, _workspace: None,
    )

    # These functions must never be reached by adoption, even on failure.
    def forbidden(*args, **kwargs):
        raise AssertionError("adoption must not copy or transcribe")

    monkeypatch.setattr("avo.timeline.delivery._copy_verified_master", forbidden)
    monkeypatch.setattr(
        "avo.final_transcript_artifacts.generate_from_master", forbidden
    )
    return SimpleNamespace(
        service=DeliveryService(workspace, clock=lambda: "2026-10-16T12:00:00Z"),
        kwargs={
            "master": master,
            "dependencies": dependencies,
            "materialization": materialization,
            "materialization_path": materialization_path,
            "transcript_artifacts": sidecars,
            "review_path": review_path,
        },
        master=master,
        heads=heads,
        sidecars=sidecars,
        review=review,
        review_path=review_path,
        snapshot=snapshot,
    )


def test_adopt_existing_preserves_master_sidecars_and_is_idempotent(adoption):
    paths = [adoption.master, *adoption.sidecars.values(), adoption.review_path]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    manifest = adoption.service.adopt_existing(**adoption.kwargs)
    assert manifest["state"] == "review-ready"
    assert Path(manifest["master"]["path"]) == adoption.master
    assert manifest["approval"] is None
    assert manifest["adoption"]["mode"] == "existing-master"
    assert adoption.service.adopt_existing(**adoption.kwargs) == manifest
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    }
    assert not (adoption.service.workspace.raw_dir / "edit" / "masters").exists()


@pytest.mark.parametrize("missing", ["json", "txt", "md", "srt"])
def test_adopt_existing_requires_all_existing_sidecars(adoption, missing):
    adoption.sidecars[missing].unlink()
    with pytest.raises(DeliveryError, match="transcript artifact"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


@pytest.mark.parametrize(
    "binding",
    [
        "candidate",
        "materialization",
        "proofPlan",
        "transcript",
        "review",
        "regressionResult",
        "approval",
        "state",
    ],
)
def test_adopt_existing_requires_exact_approved_lifecycle(adoption, binding):
    if binding == "state":
        adoption.snapshot[binding] = "rendered"
    elif binding in {"review", "regressionResult", "approval"}:
        adoption.snapshot[binding] = None
    else:
        adoption.snapshot[binding]["sha256"] = "0" * 64
    with pytest.raises(DeliveryError):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


@pytest.mark.parametrize(
    "damage",
    [
        "missing-watch",
        "window-watch",
        "coverage",
        "fail",
        "identity",
        "lock",
        "dependencies",
        "checkpoint",
    ],
)
def test_adopt_existing_revalidates_persisted_review_gate(adoption, damage):
    review = adoption.review
    watch = next(item for item in review["evidence"] if item["kind"] == "watch")
    if damage == "missing-watch":
        review["evidence"].remove(watch)
    elif damage == "window-watch":
        watch["scope"] = {
            "mode": "windows",
            "windows": [{"start": 0, "end": 1, "reason": "partial"}],
            "rationale": "partial",
        }
    elif damage == "coverage":
        watch["coverage"]["reviewedWindows"] = 0
    elif damage == "fail":
        watch["status"] = "fail"
    elif damage == "identity":
        review["candidate"]["identityHash"] = "0" * 64
    elif damage == "lock":
        review["dependencyLockSha256"] = "0" * 64
    elif damage == "dependencies":
        review["candidate"]["dependencies"]["cmap"] = "0" * 64
    else:
        review["checkpoint"] = "pre-master"
    _write(adoption.review_path, review)
    with pytest.raises(DeliveryError):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_adopt_existing_rejects_stale_active_canonical_heads(adoption):
    adoption.heads["tracks"] = "0" * 64
    with pytest.raises(DeliveryError, match="canonical"):
        adoption.service.adopt_existing(**adoption.kwargs)


@pytest.mark.parametrize("mutation", ["sidecar", "review"])
def test_adopt_existing_cannot_rebind_existing_manifest(adoption, mutation):
    adoption.service.adopt_existing(**adoption.kwargs)
    path = adoption.sidecars["srt"] if mutation == "sidecar" else adoption.review_path
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(DeliveryError, match="changed"):
        adoption.service.validate_current()


def test_adopt_existing_rejects_mismatched_transcript_source(adoption):
    path = adoption.sidecars["json"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source"]["sha256"] = "0" * 64
    _write(path, payload)
    with pytest.raises(DeliveryError, match="transcript"):
        adoption.service.adopt_existing(**adoption.kwargs)


def test_adopt_existing_rejects_unpersisted_materialization_body(adoption):
    adoption.kwargs["materialization_path"].write_text("{}", encoding="utf-8")
    with pytest.raises(DeliveryError, match="materialization"):
        adoption.service.adopt_existing(**adoption.kwargs)


@pytest.mark.parametrize(
    "damage", ["unstructured", "unobserved-frame", "failed-frame", "artifact"]
)
def test_adopt_existing_requires_complete_authentic_watch(adoption, damage):
    watch = next(
        item for item in adoption.review["evidence"] if item["kind"] == "watch"
    )
    if damage == "unstructured":
        del watch["visionCoverageManifest"]
    elif damage == "unobserved-frame":
        watch["coverage"]["observedFrames"] = [0]
    elif damage == "failed-frame":
        watch["coverage"]["failedFrames"] = [30]
    else:
        Path(watch["visionCoverageManifest"]["artifact"]["path"]).write_text(
            "changed", encoding="utf-8"
        )
    _write(adoption.review_path, adoption.review)
    with pytest.raises(DeliveryError, match="review"):
        adoption.service.adopt_existing(**adoption.kwargs)


def test_adopt_existing_cannot_erase_delivered_approval(adoption):
    adoption.service.adopt_existing(**adoption.kwargs)
    delivered = adoption.service.approve(
        actor="fixture-creator", reason="synthetic fixture only"
    )
    preserved = adoption.service.manifest_path.read_bytes()
    repeated = adoption.service.adopt_existing(**adoption.kwargs)
    assert repeated["state"] == "delivered"
    assert repeated["approval"] == delivered["approval"]
    assert adoption.service.manifest_path.read_bytes() == preserved


def test_adopt_existing_supports_native_assembly_lock_names(adoption):
    materialization = adoption.kwargs["materialization"]
    lock = materialization["canonicalInputLock"]
    for name, key in {
        "cmap": "cmapRevisionHash",
        "sync-map": "syncRevisionHash",
        "bmap": "bmapRevisionHash",
        "tracks": "tracksRevisionHash",
    }.items():
        lock[key] = lock.pop(name)
    body = {
        key: value
        for key, value in materialization.items()
        if key != "materializationHash"
    }
    materialization["materializationHash"] = content_hash(body)
    _write(adoption.kwargs["materialization_path"], materialization)
    adoption.snapshot["materialization"]["sha256"] = materialization[
        "materializationHash"
    ]
    dependencies = adoption.kwargs["dependencies"]
    dependencies["materialization"] = materialization["materializationHash"]
    identity = candidate_identity(adoption.master, dependencies, "master")
    adoption.review["candidate"] = identity
    adoption.review["dependencyLockSha256"] = dependency_lock_hash(dependencies)
    for evidence in adoption.review["evidence"]:
        evidence["candidateIdentityHash"] = identity["identityHash"]
        evidence["dependencyLockSha256"] = adoption.review["dependencyLockSha256"]
    _write(adoption.review_path, adoption.review)
    assert adoption.service.adopt_existing(**adoption.kwargs)["state"] == "review-ready"


def test_adopt_existing_requires_native_lifecycle(adoption):
    adoption.service.workspace.pipeline_run_path.unlink()
    with pytest.raises(DeliveryError, match="approved candidate"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_adopt_existing_rejects_invalid_active_owner(adoption):
    def invalid_owner(name):
        raise ValueError(f"{name} is invalid")

    adoption.service.workspace.require_active = invalid_owner
    with pytest.raises(DeliveryError, match="invalid"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_adopt_existing_rejects_changed_master(adoption):
    adoption.master.write_bytes(b"changed-approved-master")
    with pytest.raises(DeliveryError, match="materialization"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_adopt_existing_rejects_master_outside_project(adoption, tmp_path):
    outside = tmp_path.parent / "outside-approved-master.mp4"
    outside.write_bytes(adoption.master.read_bytes())
    adoption.kwargs["master"] = outside
    with pytest.raises(DeliveryError, match="outside"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert outside.read_bytes() == b"exact-approved-master"


def test_adopt_existing_rejects_missing_persisted_review(adoption):
    adoption.review_path.unlink()
    with pytest.raises(DeliveryError, match="review"):
        adoption.service.adopt_existing(**adoption.kwargs)
    assert not adoption.service.manifest_path.exists()


def test_adopt_existing_rejects_sidecar_aliases(adoption):
    adoption.sidecars["txt"] = adoption.sidecars["json"]
    with pytest.raises(DeliveryError, match="separate"):
        adoption.service.adopt_existing(**adoption.kwargs)


def test_approve_revalidates_current_adoption_heads(adoption):
    adoption.service.adopt_existing(**adoption.kwargs)
    adoption.heads["tracks"] = "0" * 64
    with pytest.raises(DeliveryError, match="canonical"):
        adoption.service.approve(
            actor="fixture-creator", reason="cannot approve stale review"
        )
    assert (
        json.loads(adoption.service.manifest_path.read_text(encoding="utf-8"))[
            "approval"
        ]
        is None
    )
