"""Freeze, transcribe, review, and approve exact final master bytes."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from avo import final_transcript_artifacts

from .contracts import dependency_lock_hash, file_fingerprint
from .review import approval_is_current
from .store import atomic_write_json, now_iso


class DeliveryError(RuntimeError):
    pass


class DeliveryService:
    def __init__(self, workspace: Any, *, clock: Callable[[], str] = now_iso):
        self.workspace = workspace
        self.clock = clock

    @property
    def manifest_path(self) -> Path:
        return self.workspace.raw_dir / "edit" / "delivery-manifest.json"

    def prepare(
        self,
        *,
        candidate: Path,
        master: Path,
        dependencies: dict[str, str],
        review_runner: Any,
        transcript_generator: Callable[
            ..., dict[str, Path]
        ] = final_transcript_artifacts.generate_from_master,
        transcript_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = Path(candidate).resolve()
        master = Path(master).resolve()
        if not candidate.is_file():
            raise DeliveryError(f"candidate does not exist: {candidate}")
        if master.exists():
            raise DeliveryError(f"immutable master already exists: {master}")
        master.parent.mkdir(parents=True, exist_ok=True)
        temporary = master.with_name(f".{master.name}.{uuid4().hex}.tmp")
        shutil.copyfile(candidate, temporary)
        temporary.replace(master)
        master_fp = file_fingerprint(master)

        edit_dir = self.workspace.raw_dir / "edit"
        sidecars = transcript_generator(
            master,
            edit_dir,
            **(transcript_options or {}),
        )
        json_path = Path(sidecars["json"])
        transcript = final_transcript_artifacts.validate_master_transcript(
            master, json_path
        )
        review = review_runner.run(
            checkpoint="deliver",
            candidate=master,
            dependencies=dict(sorted(dependencies.items())),
            render_profile="master",
            risk_windows=[],
        )
        if review.get("state") != "ai-passed":
            raise DeliveryError(
                "final master review did not pass; delivery remains blocked: "
                + str(review.get("blocker") or review.get("state"))
            )
        artifacts = {}
        for kind, path in sidecars.items():
            value = Path(path)
            artifacts[kind] = {**file_fingerprint(value), "path": str(value)}
        manifest = {
            "schemaVersion": "1.0.0",
            "state": "review-ready",
            "master": {**master_fp, "path": str(master)},
            "dependencies": dict(sorted(dependencies.items())),
            "dependencyLockSha256": dependency_lock_hash(dependencies),
            "transcript": transcript,
            "transcriptArtifacts": artifacts,
            "review": {
                "path": str(review["reviewPath"]),
                "candidateIdentityHash": review["candidate"]["identityHash"],
                "candidateSha256": review["candidate"]["sha256"],
                "dependencyLockSha256": review["dependencyLockSha256"],
                "state": review["state"],
            },
            "approval": None,
            "createdAt": self.clock(),
        }
        atomic_write_json(self.manifest_path, manifest)
        manifest["editlogRefresh"] = self.workspace.notify_editlog()
        return manifest

    def validate_current(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            raise DeliveryError("delivery manifest is missing")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        master = Path(manifest["master"]["path"])
        current = file_fingerprint(master)
        if current["sha256"] != manifest["master"]["sha256"]:
            raise DeliveryError(
                "master bytes changed; transcript, review, and approval are stale"
            )
        transcript_path = Path(manifest["transcriptArtifacts"]["json"]["path"])
        final_transcript_artifacts.validate_master_transcript(master, transcript_path)
        return manifest

    def approve(self, *, actor: str, reason: str) -> dict[str, Any]:
        manifest = self.validate_current()
        review = manifest["review"]
        approval = {
            "checkpoint": "deliver",
            "decision": "approved",
            "candidateIdentityHash": review["candidateIdentityHash"],
            "candidateSha256": review["candidateSha256"],
            "dependencyLockSha256": review["dependencyLockSha256"],
            "actor": actor,
            "reason": reason,
            "decidedAt": self.clock(),
        }
        if not approval_is_current(
            approval,
            checkpoint="deliver",
            candidate_identity_hash=review["candidateIdentityHash"],
            candidate_sha256=manifest["master"]["sha256"],
            dependency_lock_sha256=manifest["dependencyLockSha256"],
        ):
            raise DeliveryError(
                "delivery approval is not bound to the exact master identity"
            )
        manifest["approval"] = approval
        manifest["state"] = "delivered"
        atomic_write_json(self.manifest_path, manifest)
        manifest["editlogRefresh"] = self.workspace.notify_editlog()
        return manifest
