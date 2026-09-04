"""Freeze, transcribe, review, and approve exact final master bytes."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from avo import final_transcript_artifacts

from .contracts import content_hash, file_fingerprint
from .review import approval_is_current
from .store import atomic_write_json, now_iso


class DeliveryError(RuntimeError):
    pass


def _document_hash(document: dict[str, Any], hash_field: str) -> str:
    return content_hash(
        {key: value for key, value in document.items() if key != hash_field}
    )


def _validate_materialization(
    candidate: Path,
    materialization: dict[str, Any],
    materialization_path: Path | None,
) -> tuple[dict[str, Any], str]:
    if materialization.get("kind") != "assembly":
        raise DeliveryError("delivery requires a canonical assembly materialization")
    if materialization_path is None or not Path(materialization_path).is_file():
        raise DeliveryError("persisted canonical assembly materialization is missing")
    expected_hash = _document_hash(materialization, "materializationHash")
    if materialization.get("materializationHash") != expected_hash:
        raise DeliveryError("assembly materialization hash is invalid")
    candidate_fingerprint = file_fingerprint(candidate)
    output = materialization.get("output") or {}
    output_hash = str(output.get("sha256") or "")
    if candidate_fingerprint["sha256"] != output_hash or candidate_fingerprint[
        "sizeBytes"
    ] != output.get("sizeBytes"):
        raise DeliveryError(
            "candidate bytes do not match the canonical assembly materialization"
        )
    return candidate_fingerprint, output_hash


def _copy_verified_master(candidate: Path, master: Path, expected_hash: str) -> dict:
    if master.exists():
        raise DeliveryError(f"immutable master already exists: {master}")
    master.parent.mkdir(parents=True, exist_ok=True)
    temporary = master.with_name(f".{master.name}.{uuid4().hex}.tmp")
    shutil.copyfile(candidate, temporary)
    temporary_fingerprint = file_fingerprint(temporary)
    if temporary_fingerprint["sha256"] != expected_hash:
        temporary.unlink(missing_ok=True)
        raise DeliveryError("copied master bytes differ from materialized output")
    temporary.replace(master)
    master_fingerprint = file_fingerprint(master)
    if master_fingerprint["sha256"] != expected_hash:
        raise DeliveryError("copied master bytes differ from materialized output")
    return master_fingerprint


def _canonical_dependencies(
    dependencies: dict[str, str], materialization: dict[str, Any], output_hash: str
) -> dict[str, str]:
    result = dict(dependencies)
    references = {
        "materialization": materialization.get("materializationHash"),
        "delivery-fidelity-policy": materialization.get("deliveryFidelityPolicyHash"),
        "picture-lineage": materialization.get("pictureLineageHash"),
        "assembly-output": output_hash,
    }
    result.update({key: str(value) for key, value in references.items() if value})
    return dict(sorted(result.items()))


def _artifact_fingerprints(sidecars: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {
        kind: {**file_fingerprint(Path(path)), "path": str(Path(path))}
        for kind, path in sidecars.items()
    }


def _materialization_reference(
    materialization: dict[str, Any], materialization_path: Path, output_hash: str
) -> dict[str, Any]:
    policy = materialization.get("deliveryFidelityPolicy") or {}
    lineage = materialization.get("pictureLineage") or {}
    return {
        "path": str(materialization_path),
        "materializationId": materialization.get("materializationId"),
        "materializationHash": materialization.get("materializationHash"),
        "outputSha256": output_hash,
        "deliveryFidelityPolicyHash": materialization.get("deliveryFidelityPolicyHash"),
        "pictureLineageHash": materialization.get("pictureLineageHash"),
        "rootIds": list(lineage.get("rootIds") or []),
        "policy": {
            "policyId": policy.get("policyId"),
            "profileId": policy.get("profileId"),
            "policyHash": materialization.get("deliveryFidelityPolicyHash"),
            "settingSources": policy.get("settingSources") or {},
        },
        "lineage": {
            "pictureLineageHash": materialization.get("pictureLineageHash"),
            "rootIds": list(lineage.get("rootIds") or []),
        },
    }


def _validate_materialization_reference(
    reference: dict[str, Any], master_fingerprint: dict[str, Any]
) -> None:
    materialization_path = reference.get("path")
    if not materialization_path:
        raise DeliveryError("canonical assembly materialization reference is missing")
    path = Path(materialization_path)
    if not path.is_file():
        raise DeliveryError("canonical assembly materialization is missing")
    materialization = json.loads(path.read_text(encoding="utf-8"))
    actual_hash = _document_hash(materialization, "materializationHash")
    if actual_hash != materialization.get(
        "materializationHash"
    ) or actual_hash != reference.get("materializationHash"):
        raise DeliveryError("canonical assembly materialization changed")
    expected = {
        "outputSha256": (materialization.get("output") or {}).get("sha256"),
        "deliveryFidelityPolicyHash": materialization.get("deliveryFidelityPolicyHash"),
        "pictureLineageHash": materialization.get("pictureLineageHash"),
    }
    if any(reference.get(key) != value for key, value in expected.items()):
        raise DeliveryError("canonical assembly materialization references changed")
    if master_fingerprint["sha256"] != expected["outputSha256"]:
        raise DeliveryError("master bytes changed from materialized output")


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
        materialization: dict[str, Any],
        materialization_path: Path | None,
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
        _, materialized_output_hash = _validate_materialization(
            candidate, materialization, materialization_path
        )
        master_fp = _copy_verified_master(candidate, master, materialized_output_hash)
        canonical_dependencies = _canonical_dependencies(
            dependencies, materialization, materialized_output_hash
        )

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
            dependencies=canonical_dependencies,
            render_profile="master",
            risk_windows=[],
            materialization=materialization,
            materialization_path=materialization_path,
        )
        if review.get("state") != "ai-passed":
            raise DeliveryError(
                "final master review did not pass; delivery remains blocked: "
                + str(review.get("blocker") or review.get("state"))
            )
        artifacts = _artifact_fingerprints(sidecars)
        manifest = {
            "schemaVersion": "1.0.0",
            "state": "review-ready",
            "master": {**master_fp, "path": str(master)},
            "dependencies": review["candidate"]["dependencies"],
            "dependencyLockSha256": review["dependencyLockSha256"],
            "materialization": _materialization_reference(
                materialization, Path(materialization_path), materialized_output_hash
            ),
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
        _validate_materialization_reference(
            manifest.get("materialization") or {}, current
        )
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
