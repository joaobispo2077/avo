"""Canonical timeline application coordinator used by every command intent surface."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .bmap_service import BMapService
from .lifecycle import PipelineRunStore, PipelineState, TransitionFacts
from .review import approval_is_current
from .tracks import TracksService
from .workspace import TimelineWorkspace

TRACK_OWNERS = {"sound", "media", "captions", "color", "grade", "end-screen"}
_TARGETS = {
    state.value: state
    for state in PipelineState
    if state
    not in {
        PipelineState.FIXING,
        PipelineState.NEEDS_HUMAN_JUDGMENT,
        PipelineState.BLOCKED,
        PipelineState.STALE,
        PipelineState.SUPERSEDED,
    }
}


class TimelinePipeline:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        self.run_store = PipelineRunStore(workspace.pipeline_run_path)

    def initialize(self) -> dict[str, Any]:
        if self.workspace.authority != "canonical":
            self.workspace.initialize()
        return self.status()

    def status(self) -> dict[str, Any]:
        return self.workspace.status()

    @staticmethod
    def _review_facts(
        review: dict[str, Any],
        approval: dict[str, Any] | None,
        checkpoint: str,
    ) -> TransitionFacts:
        if review.get("state") != "ai-passed":
            raise ValueError(f"{checkpoint} review is not AI-passed")
        kinds = {
            item.get("kind")
            for item in review.get("evidence") or []
            if item.get("status") == "pass"
        }
        candidate = review.get("candidate") or {}
        if not approval_is_current(
            approval,
            checkpoint=checkpoint,
            candidate_identity_hash=str(candidate.get("identityHash") or ""),
            candidate_sha256=str(candidate.get("sha256") or ""),
            dependency_lock_sha256=str(review.get("dependencyLockSha256") or ""),
        ):
            raise ValueError(f"{checkpoint} human approval is not exact/current")
        return TransitionFacts(
            watch_current="watch" in kinds,
            transcript_current="transcript-analysis" in kinds,
            required_qc_passed=True,
            exact_approval=True,
        )

    def advance(self, stage: str, **payload: Any) -> dict[str, Any]:
        """Advance one persisted stage using canonical artifacts/evidence, never chat booleans."""
        self.initialize()
        target = _TARGETS.get(stage)
        if target is None:
            raise ValueError(f"unknown pipeline stage: {stage}")
        current = self.run_store.load()
        active_refs = dict(current["activeRefs"])
        facts = TransitionFacts()

        if target == PipelineState.SOURCES_READY:
            inventory = payload.get("rawInventory") or {}
            if not inventory.get("sources"):
                raise ValueError("sources-ready requires fingerprinted raw inventory")
            active_refs["rawInventory"] = inventory
        elif target == PipelineState.SYNC_READY:
            event = self.workspace.store("sync-map").effective_approval()
            if event is None:
                raise ValueError(
                    "sync-ready requires effective approved Sync or explicit N/A"
                )
            facts = TransitionFacts(sync_ready=True)
            active_refs["syncRevisionId"] = event["subject"]["revisionId"]
            active_refs["syncRevisionHash"] = event["subject"]["contentSha256"]
        elif target == PipelineState.CMAP_DRAFT:
            index = self.workspace.require_active("cmap")
            active_refs["cmapRevisionId"] = index["headRevisionId"]
        elif target == PipelineState.CUT_AI_REVIEW:
            candidate = Path(str(payload.get("candidate") or ""))
            if not candidate.is_file():
                raise ValueError("cut AI review requires encoded candidate")
            active_refs["candidatePath"] = str(candidate)
        elif target == PipelineState.CMAP_APPROVED:
            facts = self._review_facts(
                payload.get("review") or {},
                payload.get("approval"),
                "cut-proof",
            )
            candidate = payload["review"]["candidate"]
            active_refs.update(
                {
                    "cutCandidateSha256": candidate["sha256"],
                    "cutCandidateIdentityHash": candidate["identityHash"],
                }
            )
        elif target == PipelineState.BMAP_DRAFT:
            cmap_event = self.workspace.store("cmap").effective_approval()
            cut_hash = str(payload.get("cutOutputSha256") or "")
            if cmap_event is None:
                raise ValueError("BMap requires effective approved CMap")
            facts = TransitionFacts(cmap_approved=True, cut_output_hash=cut_hash)
            index = self.workspace.require_active("bmap")
            active_refs.update(
                {
                    "bmapRevisionId": index["headRevisionId"],
                    "cutOutputSha256": cut_hash,
                }
            )
        elif target == PipelineState.ASSEMBLY_AI_REVIEW:
            for artifact_type in ("bmap", "tracks", "animation"):
                index = self.workspace.require_active(artifact_type)
                active_refs[f"{artifact_type}RevisionId"] = index["headRevisionId"]
            candidate = Path(str(payload.get("candidate") or ""))
            if not candidate.is_file():
                raise ValueError("assembly AI review requires encoded candidate")
            active_refs["candidatePath"] = str(candidate)
        elif target == PipelineState.PICTURE_LOCKED:
            facts = self._review_facts(
                payload.get("review") or {},
                payload.get("approval"),
                "motion-proof",
            )
        elif target == PipelineState.FINISHING:
            pass
        elif target == PipelineState.PRE_MASTER_AI_REVIEW:
            candidate = Path(str(payload.get("candidate") or ""))
            if not candidate.is_file():
                raise ValueError("pre-master review requires encoded candidate")
            active_refs["candidatePath"] = str(candidate)
        elif target == PipelineState.MASTER_APPROVED:
            facts = self._review_facts(
                payload.get("review") or {},
                payload.get("approval"),
                "pre-master",
            )
        elif target == PipelineState.DELIVERED:
            manifest = payload.get("deliveryManifest") or {}
            if manifest.get("state") != "delivered":
                raise ValueError("delivered requires exact approved delivery manifest")
            transcript = manifest.get("transcript") or {}
            master = manifest.get("master") or {}
            if transcript.get("sourceSha256") != master.get("sha256"):
                raise ValueError("delivered requires exact final-file transcript")
            facts = TransitionFacts(
                exact_approval=True,
                final_transcript_current=True,
                final_qc_passed=True,
            )
            active_refs["masterSha256"] = master["sha256"]
        elif target == PipelineState.ARCHIVED:
            pass

        result = self.run_store.advance(
            target,
            facts,
            actor=str(payload.get("actor") or "avo.pipeline"),
            reason=str(payload.get("reason") or f"pipeline advanced to {stage}"),
            active_refs=active_refs,
        )
        return result

    def enter_blocked(
        self, *, reason: str, blockers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.run_store.enter_side_state(
            PipelineState.BLOCKED,
            actor="avo.pipeline",
            reason=reason,
            blockers=blockers,
        )

    def resume(self, *, actor: str, reason: str, recovery_event: str) -> dict[str, Any]:
        return self.run_store.resume(
            actor=actor,
            reason=reason,
            recovery_event=recovery_event,
        )

    def apply_assembly_stage(
        self,
        *,
        owner: str,
        bmap_snapshot: dict[str, Any],
        tracks_snapshot: dict[str, Any],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if owner not in TRACK_OWNERS:
            raise ValueError(f"operation cannot own Tracks/BMap state: {owner}")
        bmap_revision = BMapService(self.workspace).author(
            deepcopy(bmap_snapshot),
            actor=actor,
            reason=f"{owner}: {reason}",
        )
        tracks_revision = TracksService(self.workspace).author(
            deepcopy(tracks_snapshot),
            actor=actor,
            reason=f"{owner}: {reason}",
        )
        return {
            "owner": owner,
            "bmapRevisionId": bmap_revision["revisionId"],
            "bmapRevisionHash": bmap_revision["contentHash"],
            "tracksRevisionId": tracks_revision["revisionId"],
            "tracksRevisionHash": tracks_revision["contentHash"],
        }

    def sound(self, **request: Any) -> dict[str, Any]:
        return self.apply_assembly_stage(owner="sound", **request)

    def media(self, **request: Any) -> dict[str, Any]:
        return self.apply_assembly_stage(owner="media", **request)

    def captions(self, **request: Any) -> dict[str, Any]:
        return self.apply_assembly_stage(owner="captions", **request)

    def color(self, **request: Any) -> dict[str, Any]:
        return self.apply_assembly_stage(owner="color", **request)

    def grade(self, **request: Any) -> dict[str, Any]:
        return self.apply_assembly_stage(owner="grade", **request)

    def end_screen(self, **request: Any) -> dict[str, Any]:
        return self.apply_assembly_stage(owner="end-screen", **request)
