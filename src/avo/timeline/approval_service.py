"""Exact creator decisions bound to current review, materialization, and CMap lineage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import content_hash, dependency_lock_hash, validate_document
from .lifecycle import PipelineRunStore, PipelineState, TransitionFacts
from .review import evaluate_gate
from .workspace import TimelineWorkspace


class ApprovalService:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        self.store = workspace.store("cmap")

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
        if decision == "approved" and review["state"] != "ai-passed":
            raise ValueError("CMap approval requires current ai-passed evidence")
        if materialization.get("cmapRevisionId") != revision_id:
            raise ValueError("materialization is bound to another CMap revision")
        lock = materialization.get("canonicalInputLock") or {}
        if lock.get("cmapRevisionHash") != revision["contentHash"]:
            raise ValueError("materialization CMap hash is stale")
        candidate_hash = str((materialization.get("output") or {}).get("sha256") or "")
        if candidate_hash != review["candidate"]["sha256"]:
            raise ValueError("review candidate does not match cut materialization")
        dependencies = review["candidate"]["dependencies"]
        if dependencies.get("cmap") != revision["contentHash"]:
            raise ValueError("review is bound to another CMap revision")
        if dependencies.get("cutOutput") != candidate_hash:
            raise ValueError("review cut-output dependency does not match candidate")
        if dependencies.get("sync-map") != lock.get("syncRevisionHash"):
            raise ValueError("review Sync dependency is stale")
        if review["dependencyLockSha256"] != dependency_lock_hash(dependencies):
            raise ValueError("review dependency lock is invalid")
        evaluate_gate(
            "cut-proof",
            candidate_hash,
            dependencies,
            review["evidence"],
            candidate_identity_hash=review["candidate"]["identityHash"],
            dependency_lock_sha256=review["dependencyLockSha256"],
        )
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
                    "reviewIdentityHash": review["candidate"]["identityHash"],
                },
            )
        return event
