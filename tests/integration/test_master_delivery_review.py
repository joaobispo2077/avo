from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.contracts import content_hash, dependency_lock_hash, file_fingerprint
from avo.timeline.delivery import DeliveryError, DeliveryService
from avo.timeline.review import candidate_identity
from avo.timeline.workspace import TimelineWorkspace
from avo.transcribe import source_fingerprint


class Review:
    def run(
        self,
        *,
        checkpoint,
        candidate,
        dependencies,
        render_profile,
        risk_windows,
        materialization=None,
        materialization_path=None,
    ):
        identity = candidate_identity(candidate, dependencies, render_profile)
        path = candidate.parent / "review.json"
        path.write_text("{}", encoding="utf-8")
        return {
            "state": "ai-passed",
            "candidate": identity,
            "dependencyLockSha256": dependency_lock_hash(dependencies),
            "reviewPath": path,
        }


def transcript_generator(master: Path, edit_dir: Path, **options):
    output = edit_dir / "transcripts" / f"{master.stem}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = source_fingerprint(master)
    payload = {
        "schema_version": 1,
        "text": "fala final",
        "language_code": "pt-BR",
        "engine_language": "pt",
        "engine": "fixture",
        "engine_version": "1.0",
        "model": "fixture-ptbr",
        "source": fingerprint,
        "words": [
            {
                "text": "fala",
                "start": 0.0,
                "end": 0.4,
                "type": "word",
                "speaker_id": None,
                "probability": 1.0,
            }
        ],
    }
    output.write_text(json.dumps(payload), encoding="utf-8")
    for extension in ("srt", "txt", "md"):
        output.with_suffix(f".{extension}").write_text("fala\n", encoding="utf-8")
    return {
        "json": output,
        "srt": output.with_suffix(".srt"),
        "txt": output.with_suffix(".txt"),
        "md": output.with_suffix(".md"),
    }


def workspace(tmp_path: Path) -> TimelineWorkspace:
    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "fixture-provider",
                "videoId": "delivery",
                "rawDir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    return TimelineWorkspace.from_project(project)


def test_master_transcript_and_delivery_are_exact_byte_bound(tmp_path: Path):
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"frozen-master-candidate")
    materialization_body = {
        "schemaVersion": "1.1.0",
        "kind": "assembly",
        "materializationId": "assembly-test",
        "output": file_fingerprint(candidate),
        "deliveryFidelityPolicy": {
            "policyId": "avo.delivery-fidelity",
            "profileId": "fixture-master",
            "settingSources": {"profileId": "project"},
        },
        "deliveryFidelityPolicyHash": "d" * 64,
        "pictureLineageHash": "e" * 64,
        "pictureLineage": {"rootIds": ["output"]},
    }
    materialization = {
        **materialization_body,
        "materializationHash": content_hash(materialization_body),
    }
    materialization_path = tmp_path / "assembly.json"
    materialization_path.write_text(json.dumps(materialization), encoding="utf-8")
    service = DeliveryService(workspace(tmp_path), clock=lambda: "2026-08-14T00:00:00Z")
    master = tmp_path / "edit" / "masters" / "delivery-master-v001.mp4"
    deps = {"cmap": "a" * 64, "tracks": "b" * 64, "sourceUsage": "c" * 64}
    manifest = service.prepare(
        candidate=candidate,
        master=master,
        dependencies=deps,
        materialization=materialization,
        materialization_path=materialization_path,
        review_runner=Review(),
        transcript_generator=transcript_generator,
    )
    assert manifest["transcript"]["sourceSha256"] == manifest["master"]["sha256"]
    assert (
        manifest["materialization"]["materializationHash"]
        == materialization["materializationHash"]
    )
    assert (
        manifest["dependencyLockSha256"] == manifest["review"]["dependencyLockSha256"]
    )
    assert manifest["materialization"]["policy"] == {
        "policyId": "avo.delivery-fidelity",
        "profileId": "fixture-master",
        "policyHash": "d" * 64,
        "settingSources": {"profileId": "project"},
    }
    assert manifest["materialization"]["lineage"] == {
        "pictureLineageHash": "e" * 64,
        "rootIds": ["output"],
    }
    delivered = service.approve(actor="creator", reason="exact master approved")
    assert delivered["state"] == "delivered"

    master.write_bytes(master.read_bytes() + b"mutation")
    with pytest.raises(DeliveryError, match="changed"):
        service.validate_current()
    with pytest.raises(DeliveryError):
        service.approve(actor="creator", reason="old approval cannot survive")


def test_prepare_rejects_changed_copy_before_publishing_master(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"canonical-candidate")
    body = {
        "schemaVersion": "1.1.0",
        "kind": "assembly",
        "materializationId": "assembly-copy-check",
        "output": file_fingerprint(candidate),
        "deliveryFidelityPolicyHash": "d" * 64,
        "pictureLineageHash": "e" * 64,
        "pictureLineage": {"rootIds": ["output"]},
    }
    materialization = {**body, "materializationHash": content_hash(body)}
    materialization_path = tmp_path / "assembly.json"
    materialization_path.write_text(json.dumps(materialization), encoding="utf-8")

    def corrupt_copy(_source, target):
        Path(target).write_bytes(b"not-the-candidate")

    monkeypatch.setattr("avo.timeline.delivery.shutil.copyfile", corrupt_copy)
    master = tmp_path / "edit" / "masters" / "master.mp4"
    with pytest.raises(DeliveryError, match="copied master bytes differ"):
        DeliveryService(workspace(tmp_path)).prepare(
            candidate=candidate,
            master=master,
            dependencies={},
            materialization=materialization,
            materialization_path=materialization_path,
            review_runner=Review(),
            transcript_generator=transcript_generator,
        )
    assert not master.exists()
