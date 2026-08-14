from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.contracts import dependency_lock_hash
from avo.timeline.delivery import DeliveryError, DeliveryService
from avo.timeline.review import candidate_identity
from avo.timeline.workspace import TimelineWorkspace
from avo.transcribe import source_fingerprint


class Review:
    def run(self, *, checkpoint, candidate, dependencies, render_profile, risk_windows):
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
    project.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "provider": "bishop",
        "videoId": "delivery",
        "rawDir": str(tmp_path),
    }), encoding="utf-8")
    return TimelineWorkspace.from_project(project)


def test_master_transcript_and_delivery_are_exact_byte_bound(tmp_path: Path):
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"frozen-master-candidate")
    service = DeliveryService(workspace(tmp_path), clock=lambda: "2026-08-14T00:00:00Z")
    master = tmp_path / "edit" / "masters" / "delivery-master-v001.mp4"
    deps = {"cmap": "a" * 64, "tracks": "b" * 64, "sourceUsage": "c" * 64}
    manifest = service.prepare(
        candidate=candidate,
        master=master,
        dependencies=deps,
        review_runner=Review(),
        transcript_generator=transcript_generator,
    )
    assert manifest["transcript"]["sourceSha256"] == manifest["master"]["sha256"]
    delivered = service.approve(actor="creator", reason="exact master approved")
    assert delivered["state"] == "delivered"

    master.write_bytes(master.read_bytes() + b"mutation")
    with pytest.raises(DeliveryError, match="changed"):
        service.validate_current()
    with pytest.raises(DeliveryError):
        service.approve(actor="creator", reason="old approval cannot survive")
