"""Exact creator decisions bound to current review, materialization, and CMap lineage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import content_hash, dependency_lock_hash, validate_document
from .lifecycle import PipelineRunStore, PipelineState, TransitionFacts
from .review import GateError, evaluate_gate, validate_evidence_integrity
from .workspace import TimelineWorkspace


def _require_cut_proof_integrity(review: dict[str, Any], candidate_hash: str) -> None:
    dependencies = review["candidate"]["dependencies"]
    try:
        validate_evidence_integrity(
            "cut-proof",
            candidate_hash,
            dependencies,
            review["evidence"],
            candidate_identity_hash=review["candidate"]["identityHash"],
            dependency_lock_sha256=review["dependencyLockSha256"],
        )
        if review["state"] == "ai-passed":
            evaluate_gate(
                "cut-proof",
                candidate_hash,
                dependencies,
                review["evidence"],
                candidate_identity_hash=review["candidate"]["identityHash"],
                dependency_lock_sha256=review["dependencyLockSha256"],
            )
    except GateError as error:
        raise ValueError(str(error)) from error


class ApprovalService:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        self.store = workspace.store("cmap")

    def _require_candidate_snapshot(
        self, candidate_sha256: str, candidate_size: int | None = None
    ) -> dict[str, Any] | None:
        from .pipeline import TimelinePipeline

        snapshot = TimelinePipeline(self.workspace).active_candidate_snapshot()
        if snapshot is None:
            return None
        candidate = snapshot["candidate"]
        if candidate["sha256"] != candidate_sha256 or (
            candidate_size is not None and candidate["sizeBytes"] != candidate_size
        ):
            raise ValueError("approval candidate bytes differ from active snapshot")
        if snapshot["state"] not in {"reviewing", "needs-human"}:
            raise ValueError("approval requires the active reviewed candidate snapshot")
        return snapshot

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"cannot load approval input {path}: {error}") from error
        if not isinstance(document, dict):
            raise ValueError(f"approval input must be an object: {path}")
        return document

    def decide(
        self,
        *,
        decision: str,
        revision_id: str,
        review_path: Path,
        materialization_path: Path,
        actor: str,
        reason: str,
        scope: str = "exact-cut-proof",
    ) -> dict[str, Any]:
        review = self._load(review_path)
        validate_document(review, "avo.review-evidence.schema.json")
        materialization = self._load(materialization_path)
        revision = self.store.revision(revision_id)
        if self.store.load_index()["headRevisionId"] != revision_id:
            raise ValueError("CMap decision requires the current head revision")
        if review["checkpoint"] != "cut-proof":
            raise ValueError("CMap decision requires a cut-proof review")
        if decision == "approved" and review["state"] not in {
            "ai-passed",
            "needs-human-judgment",
        }:
            raise ValueError("CMap approval requires current review evidence")
        if materialization.get("cmapRevisionId") != revision_id:
            raise ValueError("materialization is bound to another CMap revision")
        lock = materialization.get("canonicalInputLock") or {}
        if lock.get("cmapRevisionHash") != revision["contentHash"]:
            raise ValueError("materialization CMap hash is stale")
        candidate_hash = str((materialization.get("output") or {}).get("sha256") or "")
        if candidate_hash != review["candidate"]["sha256"]:
            raise ValueError("review candidate does not match cut materialization")
        active_snapshot = self._require_candidate_snapshot(
            candidate_hash, review["candidate"].get("byteSize")
        )
        if active_snapshot is not None:
            materialization_hash = str(materialization.get("materializationHash") or "")
            if active_snapshot["materialization"]["sha256"] != materialization_hash:
                raise ValueError(
                    "approval materialization differs from active snapshot"
                )
            proof_plan_hash = str(materialization.get("proofPlanHash") or "")
            if (
                proof_plan_hash
                and active_snapshot["proofPlan"]["sha256"] != proof_plan_hash
            ):
                raise ValueError("approval proof plan differs from active snapshot")
            if active_snapshot["review"] is not None and active_snapshot["review"][
                "sha256"
            ] != content_hash(review):
                raise ValueError("approval review differs from active snapshot")
        dependencies = review["candidate"]["dependencies"]
        if dependencies.get("cmap") != revision["contentHash"]:
            raise ValueError("review is bound to another CMap revision")
        if dependencies.get("cutOutput") != candidate_hash:
            raise ValueError("review cut-output dependency does not match candidate")
        if dependencies.get("sync-map") != lock.get("syncRevisionHash"):
            raise ValueError("review Sync dependency is stale")
        if review["dependencyLockSha256"] != dependency_lock_hash(dependencies):
            raise ValueError("review dependency lock is invalid")
        _require_cut_proof_integrity(review, candidate_hash)
        regression_result = next(
            (
                evidence.get("regressionResult")
                for evidence in review.get("evidence") or []
                if evidence.get("regressionResult")
            ),
            None,
        )
        if (
            active_snapshot is not None
            and active_snapshot["regressionResult"] is None
            and regression_result is None
        ):
            raise ValueError("candidate approval requires an exact regression result")
        expected_materialization_hash = materialization.get("materializationHash")
        body = {
            key: value
            for key, value in materialization.items()
            if key != "materializationHash"
        }
        if (
            expected_materialization_hash
            and expected_materialization_hash != content_hash(body)
        ):
            raise ValueError("cut materialization record hash mismatch")
        event = self.store.record_decision(
            decision=decision,
            revision_id=revision_id,
            revision_hash=revision["contentHash"],
            candidate_hash=candidate_hash,
            dependency_hashes=dependencies,
            actor={"type": "user", "id": actor},
            checkpoint="cut-proof",
            scope=scope,
            reason=reason,
            evidence_bundle_hash=content_hash(review),
        )
        if active_snapshot is not None:
            from .pipeline import TimelinePipeline

            plan_sha256 = active_snapshot["proofPlan"]["sha256"]
            review_binding = {
                "artifactId": f"{review['checkpoint']}-review",
                "sha256": content_hash(review),
                "candidateSha256": candidate_hash,
                "proofPlanSha256": plan_sha256,
            }
            regression_binding = (
                {
                    **active_snapshot["regressionResult"],
                    "candidateSha256": candidate_hash,
                }
                if active_snapshot["regressionResult"] is not None
                else {
                    "artifactId": "regression-result",
                    "sha256": content_hash(regression_result),
                    "candidateSha256": candidate_hash,
                }
            )
            TimelinePipeline(self.workspace).record_candidate_snapshot(
                state="approved" if decision == "approved" else "rejected",
                candidate=active_snapshot["candidate"],
                iteration_id=active_snapshot["iterationId"],
                proof_plan={
                    **active_snapshot["proofPlan"],
                    "iterationId": active_snapshot["iterationId"],
                },
                materialization={
                    **active_snapshot["materialization"],
                    "candidateSha256": candidate_hash,
                },
                transcript={
                    "fingerprint": active_snapshot["transcript"],
                    "sourceSha256": candidate_hash,
                },
                review=(
                    {
                        **active_snapshot["review"],
                        "candidateSha256": candidate_hash,
                        "proofPlanSha256": plan_sha256,
                    }
                    if active_snapshot["review"] is not None
                    else review_binding
                ),
                regression_result=regression_binding,
                approval=(
                    {
                        "artifactId": str(event["eventId"]),
                        "sha256": content_hash(event),
                        "candidateSha256": candidate_hash,
                    }
                    if decision == "approved"
                    else None
                ),
                expected_active_snapshot_hash=active_snapshot["snapshotHash"],
            )
        run_store = PipelineRunStore(self.workspace.pipeline_run_path)
        run = run_store.load()
        if (
            decision == "approved"
            and run["mainState"] == PipelineState.CUT_AI_REVIEW.value
            and run["sideState"] is None
        ):
            run_store.advance(
                PipelineState.CMAP_APPROVED,
                TransitionFacts(watch_current=True, transcript_current=True),
                actor=actor,
                reason=reason,
                active_refs={
                    **run["activeRefs"],
                    "cmapRevisionId": revision_id,
                    "cutOutputSha256": candidate_hash,
                    **(
                        {}
                        if active_snapshot is not None
                        else {"reviewIdentityHash": review["candidate"]["identityHash"]}
                    ),
                },
            )
        event["editlogRefresh"] = self.workspace.notify_editlog()
        return event
