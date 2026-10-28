"""Freeze, transcribe, review, and approve exact final master bytes."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from copy import deepcopy
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
    if materialization.get("kind") not in {"assembly", "proof-plan"}:
        raise DeliveryError(
            "delivery requires a canonical assembly or native proof materialization"
        )
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
    if materialization.get("kind") == "proof-plan":
        from .approval_service import native_proof_dependencies

        try:
            required = native_proof_dependencies(materialization)
        except (ValueError, RuntimeError) as error:
            raise DeliveryError(
                f"native proof materialization is invalid: {error}"
            ) from error
        if any(
            key in result and result[key] != digest for key, digest in required.items()
        ):
            raise DeliveryError("native proof delivery dependencies are stale")
        return dict(sorted({**result, **required}.items()))
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
    reference = {
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
    if materialization.get("kind") == "proof-plan":
        reference.update(
            {
                "kind": "proof-plan",
                "proofPlanId": materialization["proofPlanId"],
                "proofPlanHash": materialization["proofPlanHash"],
                "preflightHash": materialization["preflightHash"],
                "microproofGateHash": materialization["microproofGateHash"],
            }
        )
    return reference


def _validate_materialization_reference(
    reference: dict[str, Any], master_fingerprint: dict[str, Any]
) -> dict[str, Any]:
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
    _require_native_reference(reference, materialization)
    return materialization


def _require_native_reference(reference, materialization):
    if materialization.get("kind") != "proof-plan":
        return
    expected = {
        key: materialization.get(key)
        for key in (
            "proofPlanId",
            "proofPlanHash",
            "preflightHash",
            "microproofGateHash",
        )
    }
    expected["kind"] = "proof-plan"
    if any(reference.get(key) != value for key, value in expected.items()):
        raise DeliveryError("native proof delivery references changed")


def _load_document(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DeliveryError(f"cannot load {label}: {path}") from error
    if not isinstance(document, dict):
        raise DeliveryError(f"{label} must be an object: {path}")
    return document


def _existing_transcript_artifacts(
    paths: dict[str, Path], raw_dir: Path
) -> dict[str, Path]:
    if set(paths) != {"json", "txt", "md", "srt"}:
        raise DeliveryError(
            "existing transcript artifacts require JSON, TXT, MD and SRT"
        )
    resolved = {kind: Path(path).resolve() for kind, path in paths.items()}
    if len(set(resolved.values())) != 4:
        raise DeliveryError("existing transcript artifacts must be separate files")
    for kind, path in resolved.items():
        if (
            not path.is_relative_to(raw_dir.resolve())
            or not path.is_file()
            or path.stat().st_size == 0
        ):
            raise DeliveryError(
                f"existing transcript artifact is missing or unsafe: {kind}"
            )
    return resolved


def _require_current_adoption_dependencies(
    workspace: Any, materialization: dict[str, Any], dependencies: dict[str, str]
) -> None:
    from .approval_service import require_current_candidate_dependencies

    try:
        require_current_candidate_dependencies(workspace, materialization, dependencies)
    except (ValueError, RuntimeError) as error:
        raise DeliveryError(str(error)) from error


def _validate_existing_review(
    path: Path, master: Path, fingerprint: dict[str, Any], dependencies: dict[str, str]
) -> dict[str, Any]:
    from .approval_service import require_candidate_review

    review = _load_document(path, "delivery review")
    try:
        require_candidate_review(
            review,
            checkpoint="deliver",
            candidate=master,
            fingerprint=fingerprint,
            dependencies=dependencies,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise DeliveryError(f"existing delivery review is invalid: {error}") from error
    return review


def _human_final_review(
    workspace, path, master, fingerprint, materialization, dependencies
):
    from .approval_service import require_human_final_disposition

    try:
        disposition = require_human_final_disposition(
            workspace,
            path,
            candidate=master,
            fingerprint=fingerprint,
            materialization=materialization,
            dependencies=dependencies,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise DeliveryError(f"human-final disposition is invalid: {error}") from error
    return {
        "kind": "human-final-disposition",
        "path": str(path),
        "state": "human-approved",
        "candidateIdentityHash": disposition["candidateIdentityHash"],
        "candidateSha256": disposition["candidateSha256"],
        "dependencyLockSha256": disposition["dependencyLockSha256"],
    }


def _require_native_delivery_materialization(
    workspace, candidate, materialization, path, dependencies
):
    from .approval_service import require_native_proof_materialization

    if _load_document(path, "native proof materialization") != materialization:
        raise DeliveryError(
            "persisted native proof materialization differs from supplied record"
        )
    try:
        expected = require_native_proof_materialization(
            workspace, materialization, candidate
        )
        if any(dependencies.get(key) != value for key, value in expected.items()):
            raise DeliveryError(
                "native delivery materialization dependencies are stale"
            )
    except (OSError, ValueError, RuntimeError) as error:
        raise DeliveryError(
            f"native delivery materialization is invalid: {error}"
        ) from error


def _motion_delivery_metadata(
    package: dict[str, Any] | Path, candidate: Path, dependencies: dict[str, str]
) -> dict[str, Any]:
    from .review import validate_code_drawn_review

    if isinstance(package, (str, Path)):
        package = _load_document(Path(package), "code-drawn motion review")
    if not isinstance(package, dict):
        raise DeliveryError("delivery motion review must be an exact candidate package")
    try:
        evidence = validate_code_drawn_review(
            package,
            candidate=candidate,
            dependencies=dependencies,
            render_profile="master",
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise DeliveryError(
            f"delivery motion review is invalid or stale: {error}"
        ) from error
    if evidence["status"] == "fail":
        raise DeliveryError("delivery motion review has unresolved blocking findings")
    return {
        "engine": "code-drawn",
        "sources": deepcopy(package["sources"]),
        "output": deepcopy(package["candidateContract"]),
        "review": deepcopy(evidence["reviewContext"]["codeDrawnReview"]),
    }


def _require_native_motion_sources(materialization, metadata):
    lock = materialization.get("canonicalInputLock") or {}
    for source in metadata["sources"]:
        expected = {
            "generated:" + source["assetId"]: source["recordHash"],
            "input-lock:" + source["instanceId"]: source["inputLockHash"],
        }
        if any(lock.get(key) != digest for key, digest in expected.items()):
            raise DeliveryError(
                "motion review source is absent from native proof input lock"
            )


def _validate_motion_delivery(manifest: dict[str, Any], master: Path) -> None:
    if "motion" not in manifest:
        return
    expected = manifest["motion"]
    if not isinstance(expected, dict) or not (expected.get("review") or {}).get("path"):
        raise DeliveryError("delivery motion review reference is missing")
    current = _motion_delivery_metadata(
        Path(expected["review"]["path"]), master, manifest["dependencies"]
    )
    if current != expected:
        raise DeliveryError("delivery motion source/review identity changed")


class DeliveryService:
    def __init__(self, workspace: Any, *, clock: Callable[[], str] = now_iso):
        self.workspace = workspace
        self.clock = clock

    @property
    def manifest_path(self) -> Path:
        return self.workspace.raw_dir / "edit" / "delivery-manifest.json"

    def _require_candidate_snapshot(
        self,
        fingerprint: dict[str, Any],
        *,
        state: str = "approved",
    ) -> dict[str, Any] | None:
        from .pipeline import TimelinePipeline

        if not self.workspace.pipeline_run_path.is_file():
            return None
        pipeline = TimelinePipeline(self.workspace)
        snapshot = pipeline.active_candidate_snapshot()
        if snapshot is None:
            return None
        candidate = snapshot["candidate"]
        if candidate["sha256"] != fingerprint.get("sha256") or candidate[
            "sizeBytes"
        ] != fingerprint.get("sizeBytes"):
            raise DeliveryError("master bytes differ from active reviewed snapshot")
        if snapshot["state"] != state:
            raise DeliveryError(f"delivery requires active {state} candidate snapshot")
        return {
            "snapshotId": snapshot["snapshotId"],
            "sha256": snapshot["snapshotHash"],
        }

    def _require_native_candidate_snapshot(
        self, fingerprint, materialization, dependencies
    ):
        from .pipeline import TimelinePipeline

        reference = self._require_candidate_snapshot(fingerprint)
        snapshot = TimelinePipeline(self.workspace).active_candidate_snapshot()
        if reference is None or snapshot is None:
            raise DeliveryError(
                "native delivery requires an approved candidate snapshot"
            )
        exact = (
            (snapshot.get("materialization") or {}).get("sha256")
            == materialization["materializationHash"],
            (snapshot.get("proofPlan") or {}).get("sha256")
            == dependencies["proof-plan"],
            all(
                snapshot.get(key) for key in ("review", "regressionResult", "approval")
            ),
        )
        if not all(exact):
            raise DeliveryError("native delivery candidate snapshot bindings are stale")
        return reference

    def _preparation_context(
        self,
        candidate,
        materialization,
        materialization_path,
        dependencies,
        motion_review,
    ):
        candidate_fingerprint, materialized_output_hash = _validate_materialization(
            candidate, materialization, materialization_path
        )
        canonical_dependencies = _canonical_dependencies(
            dependencies, materialization, materialized_output_hash
        )
        if materialization.get("kind") == "proof-plan":
            _require_native_delivery_materialization(
                self.workspace,
                candidate,
                materialization,
                Path(materialization_path),
                canonical_dependencies,
            )
            candidate_snapshot = self._require_native_candidate_snapshot(
                candidate_fingerprint, materialization, canonical_dependencies
            )
        else:
            candidate_snapshot = self._require_candidate_snapshot(candidate_fingerprint)
        motion_metadata = (
            _motion_delivery_metadata(motion_review, candidate, canonical_dependencies)
            if motion_review is not None
            else None
        )
        if motion_metadata is not None and materialization.get("kind") == "proof-plan":
            _require_native_motion_sources(materialization, motion_metadata)
        return (
            materialized_output_hash,
            candidate_snapshot,
            canonical_dependencies,
            motion_metadata,
        )

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
        motion_review: dict[str, Any] | Path | None = None,
    ) -> dict[str, Any]:
        candidate = Path(candidate).resolve()
        master = Path(master).resolve()
        if not candidate.is_file():
            raise DeliveryError(f"candidate does not exist: {candidate}")
        (
            materialized_output_hash,
            candidate_snapshot,
            canonical_dependencies,
            motion_metadata,
        ) = self._preparation_context(
            candidate,
            materialization,
            materialization_path,
            dependencies,
            motion_review,
        )
        master_fp = _copy_verified_master(candidate, master, materialized_output_hash)

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
        if materialization.get("kind") == "proof-plan":
            _validate_existing_review(
                Path(review["reviewPath"]), master, master_fp, canonical_dependencies
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
        if motion_metadata is not None:
            manifest["motion"] = motion_metadata
        if candidate_snapshot is not None:
            manifest["candidateSnapshot"] = candidate_snapshot
        atomic_write_json(self.manifest_path, manifest)
        manifest["editlogRefresh"] = self.workspace.notify_editlog()
        return manifest

    def _require_adoption_snapshot(
        self,
        fingerprint: dict[str, Any],
        materialization: dict[str, Any],
        dependencies: dict[str, str],
        transcript: dict[str, Any],
    ) -> dict[str, Any]:
        from .pipeline import TimelinePipeline

        reference = self._require_candidate_snapshot(fingerprint)
        if reference is None:
            raise DeliveryError(
                "existing-master adoption requires an approved candidate snapshot"
            )
        snapshot = TimelinePipeline(self.workspace).active_candidate_snapshot()
        if snapshot is None:
            raise DeliveryError("approved candidate snapshot is no longer active")
        exact = (
            snapshot["snapshotHash"] == reference["sha256"],
            snapshot["materialization"]["sha256"]
            == materialization["materializationHash"],
            snapshot["proofPlan"]["sha256"] == dependencies.get("proof-plan"),
            all(
                snapshot.get(key) for key in ("review", "regressionResult", "approval")
            ),
            all(
                (snapshot.get("transcript") or {}).get(key) == transcript[key]
                for key in ("sha256", "sizeBytes")
            ),
        )
        if not all(exact):
            raise DeliveryError(
                "existing-master candidate lifecycle binding is stale or incomplete"
            )
        return reference

    def adopt_existing(
        self,
        *,
        master: Path,
        dependencies: dict[str, str],
        materialization: dict[str, Any],
        materialization_path: Path,
        transcript_artifacts: dict[str, Path],
        review_path: Path | None = None,
        human_final_disposition_path: Path | None = None,
    ) -> dict[str, Any]:
        """Register an existing master and exact completed evidence without producing media."""
        if (review_path is None) == (human_final_disposition_path is None):
            raise DeliveryError(
                "review and human-final disposition are exclusive; provide exactly one"
            )
        if materialization.get("kind") != "assembly":
            raise DeliveryError(
                "existing-master adoption requires an assembly materialization"
            )
        master = Path(master).resolve()
        materialization_path = Path(materialization_path).resolve()
        if (
            not master.is_relative_to(self.workspace.raw_dir.resolve())
            or not master.is_file()
        ):
            raise DeliveryError(
                f"existing master is missing or outside the project: {master}"
            )
        if (
            _load_document(materialization_path, "assembly materialization")
            != materialization
        ):
            raise DeliveryError(
                "persisted assembly materialization differs from supplied record"
            )
        fingerprint, output_hash = _validate_materialization(
            master, materialization, materialization_path
        )
        canonical_dependencies = _canonical_dependencies(
            dependencies, materialization, output_hash
        )
        _require_current_adoption_dependencies(
            self.workspace, materialization, canonical_dependencies
        )
        sidecars = _existing_transcript_artifacts(
            transcript_artifacts, self.workspace.raw_dir
        )
        try:
            transcript = final_transcript_artifacts.validate_master_transcript(
                master, sidecars["json"]
            )
        except (OSError, ValueError) as error:
            raise DeliveryError(
                f"existing master transcript is invalid: {error}"
            ) from error
        artifacts = _artifact_fingerprints(sidecars)
        review, snapshot, adoption = self._adoption_review_context(
            master,
            fingerprint,
            materialization,
            canonical_dependencies,
            artifacts["json"],
            review_path,
            human_final_disposition_path,
        )
        if self.manifest_path.exists():
            existing = self.validate_current()
            same_adoption = (
                existing.get("adoption", {}).get("mode") == "existing-master",
                existing["master"]["path"] == str(master),
                existing["dependencies"] == canonical_dependencies,
                existing["transcriptArtifacts"] == artifacts,
                existing.get("adoption") == adoption,
                existing["review"] == review,
            )
            if not all(same_adoption):
                raise DeliveryError(
                    "immutable delivery manifest differs from existing adoption"
                )
            return existing
        manifest = {
            "schemaVersion": "1.0.0",
            "state": "review-ready",
            "master": {**fingerprint, "path": str(master)},
            "dependencies": canonical_dependencies,
            "dependencyLockSha256": review["dependencyLockSha256"],
            "materialization": _materialization_reference(
                materialization, Path(materialization_path), output_hash
            ),
            "transcript": transcript,
            "transcriptArtifacts": artifacts,
            "review": review,
            "adoption": adoption,
            "approval": None,
            "createdAt": self.clock(),
        }
        if snapshot is not None:
            manifest["candidateSnapshot"] = snapshot
        atomic_write_json(self.manifest_path, manifest)
        self.workspace.notify_editlog()
        return manifest

    def _adoption_review_context(
        self,
        master,
        fingerprint,
        materialization,
        dependencies,
        transcript,
        review_path,
        human_final_disposition_path,
    ):
        if human_final_disposition_path is not None:
            path = Path(human_final_disposition_path).resolve()
            review = _human_final_review(
                self.workspace, path, master, fingerprint, materialization, dependencies
            )
            reference = {"path": str(path), **file_fingerprint(path)}
            return (
                review,
                None,
                {"mode": "existing-master", "humanFinalDisposition": reference},
            )
        path = Path(review_path).resolve()
        snapshot = self._require_adoption_snapshot(
            fingerprint, materialization, dependencies, transcript
        )
        review = _validate_existing_review(path, master, fingerprint, dependencies)
        reference = {
            "path": str(path),
            "candidateIdentityHash": review["candidate"]["identityHash"],
            "candidateSha256": review["candidate"]["sha256"],
            "dependencyLockSha256": review["dependencyLockSha256"],
            "state": review["state"],
        }
        return (
            reference,
            snapshot,
            {"mode": "existing-master", "reviewFingerprint": file_fingerprint(path)},
        )

    def _validate_adoption(
        self, manifest: dict[str, Any], current: dict[str, Any]
    ) -> None:
        materialization = _load_document(
            Path(manifest["materialization"]["path"]), "assembly materialization"
        )
        _require_current_adoption_dependencies(
            self.workspace, materialization, manifest["dependencies"]
        )
        for kind, artifact in manifest["transcriptArtifacts"].items():
            if file_fingerprint(Path(artifact["path"])) != {
                key: value for key, value in artifact.items() if key != "path"
            }:
                raise DeliveryError(f"existing transcript artifact changed: {kind}")
        human_reference = manifest["adoption"].get("humanFinalDisposition")
        if human_reference is not None:
            self._validate_human_adoption(
                manifest, current, materialization, human_reference
            )
            return
        review_path = Path(manifest["review"]["path"])
        if file_fingerprint(review_path) != manifest["adoption"]["reviewFingerprint"]:
            raise DeliveryError("existing delivery review changed")
        self._require_adoption_snapshot(
            current,
            materialization,
            manifest["dependencies"],
            manifest["transcriptArtifacts"]["json"],
        )
        _validate_existing_review(
            review_path,
            Path(manifest["master"]["path"]),
            current,
            manifest["dependencies"],
        )

    def _validate_human_adoption(self, manifest, current, materialization, reference):
        path = Path(reference["path"])
        if file_fingerprint(path) != {
            key: value for key, value in reference.items() if key != "path"
        }:
            raise DeliveryError("human-final disposition changed")
        expected = _human_final_review(
            self.workspace,
            path,
            Path(manifest["master"]["path"]),
            current,
            materialization,
            manifest["dependencies"],
        )
        if manifest["review"] != expected:
            raise DeliveryError("human-final delivery identity changed")

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
        materialization = _validate_materialization_reference(
            manifest.get("materialization") or {}, current
        )
        expected_snapshot = manifest.get("candidateSnapshot")
        if expected_snapshot is not None:
            active_snapshot = self._require_candidate_snapshot(current)
            if active_snapshot != expected_snapshot:
                raise DeliveryError("delivery candidate snapshot is stale")
        if manifest.get("adoption", {}).get("mode") == "existing-master":
            self._validate_adoption(manifest, current)

        if materialization.get("kind") == "proof-plan":
            materialization = _load_document(
                Path(manifest["materialization"]["path"]),
                "native proof materialization",
            )
            _require_native_delivery_materialization(
                self.workspace,
                master,
                materialization,
                Path(manifest["materialization"]["path"]),
                manifest["dependencies"],
            )
            self._require_native_candidate_snapshot(
                current, materialization, manifest["dependencies"]
            )
            if "motion" in manifest:
                _require_native_motion_sources(materialization, manifest["motion"])
            _validate_existing_review(
                Path(manifest["review"]["path"]),
                master,
                current,
                manifest["dependencies"],
            )
        _validate_motion_delivery(manifest, master)
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
