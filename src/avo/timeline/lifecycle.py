"""Canonical AVO pipeline state machine and transition guards."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PipelineState(str, Enum):
    INTAKE = "intake"
    SOURCES_READY = "sources-ready"
    SYNC_READY = "sync-ready"
    CMAP_DRAFT = "cmap-draft"
    CUT_AI_REVIEW = "cut-ai-review"
    CMAP_APPROVED = "cmap-approved"
    BMAP_DRAFT = "bmap-draft"
    ASSEMBLY_AI_REVIEW = "assembly-ai-review"
    PICTURE_LOCKED = "picture-locked"
    FINISHING = "finishing"
    PRE_MASTER_AI_REVIEW = "pre-master-ai-review"
    MASTER_APPROVED = "master-approved"
    DELIVERED = "delivered"
    ARCHIVED = "archived"
    FIXING = "fixing"
    NEEDS_HUMAN_JUDGMENT = "needs-human-judgment"
    BLOCKED = "blocked"
    STALE = "stale"
    SUPERSEDED = "superseded"


MAIN_SEQUENCE = (
    PipelineState.INTAKE,
    PipelineState.SOURCES_READY,
    PipelineState.SYNC_READY,
    PipelineState.CMAP_DRAFT,
    PipelineState.CUT_AI_REVIEW,
    PipelineState.CMAP_APPROVED,
    PipelineState.BMAP_DRAFT,
    PipelineState.ASSEMBLY_AI_REVIEW,
    PipelineState.PICTURE_LOCKED,
    PipelineState.FINISHING,
    PipelineState.PRE_MASTER_AI_REVIEW,
    PipelineState.MASTER_APPROVED,
    PipelineState.DELIVERED,
    PipelineState.ARCHIVED,
)
SIDE_STATES = {
    PipelineState.FIXING,
    PipelineState.NEEDS_HUMAN_JUDGMENT,
    PipelineState.BLOCKED,
    PipelineState.STALE,
    PipelineState.SUPERSEDED,
}


@dataclass(frozen=True)
class TransitionFacts:
    sync_ready: bool = False
    cmap_approved: bool = False
    cut_output_hash: str = ""
    watch_current: bool = False
    transcript_current: bool = False
    required_qc_passed: bool = False
    exact_approval: bool = False
    final_transcript_current: bool = False
    final_qc_passed: bool = False


class LifecycleError(RuntimeError):
    pass


_HUMAN_GATE_TARGETS = {
    PipelineState.CMAP_APPROVED,
    PipelineState.PICTURE_LOCKED,
    PipelineState.MASTER_APPROVED,
}


def transition(
    current: PipelineState | str,
    target: PipelineState | str,
    facts: TransitionFacts,
) -> PipelineState:
    current = PipelineState(current)
    target = PipelineState(target)
    if target in SIDE_STATES:
        return target
    if current in SIDE_STATES:
        raise LifecycleError(
            "side-state recovery requires an explicit resume transition"
        )
    try:
        expected = MAIN_SEQUENCE[MAIN_SEQUENCE.index(current) + 1]
    except (ValueError, IndexError) as exc:
        raise LifecycleError(f"no forward transition from {current.value}") from exc
    if target != expected:
        raise LifecycleError(
            f"invalid transition {current.value} -> {target.value}; expected {expected.value}"
        )
    if target == PipelineState.SYNC_READY and not facts.sync_ready:
        raise LifecycleError(
            "sync-ready requires resolved or not-applicable sync evidence"
        )
    if target == PipelineState.BMAP_DRAFT:
        if not facts.cmap_approved:
            raise LifecycleError("bmap-draft requires the latest approved CMap")
        if len(facts.cut_output_hash) != 64:
            raise LifecycleError("bmap-draft requires exact cut-output sha256")
    if target in _HUMAN_GATE_TARGETS:
        if not facts.watch_current:
            raise LifecycleError("human gate requires current Watch evidence")
        if not facts.transcript_current:
            raise LifecycleError("human gate requires current candidate transcript")
    if target == PipelineState.DELIVERED:
        if not facts.exact_approval:
            raise LifecycleError("delivery requires exact master approval")
        if not facts.final_transcript_current:
            raise LifecycleError("delivery requires final-file transcript")
        if not facts.final_qc_passed:
            raise LifecycleError("delivery requires final-file QC")
    return target


class PipelineRunStore:
    """Persist the lifecycle state and explicit recovery history."""

    def __init__(self, path, *, clock=None):
        from pathlib import Path

        from .store import now_iso

        self.path = Path(path)
        self.clock = clock or now_iso

    def _validate(self, document):
        from .contracts import ContractError, validate_document

        try:
            validate_document(document, "avo.pipeline-run.schema.json")
        except ContractError as exc:
            raise LifecycleError(f"invalid pipeline run: {exc}") from exc

    def initialize(
        self,
        *,
        run_id,
        video_id,
        provider,
        project_path,
        command="pipeline",
        mode="Owns",
        parent_timeline_ref=None,
    ):
        from .store import atomic_write_json

        if self.path.exists():
            return self.load()
        timestamp = self.clock()
        origin = {"command": command, "mode": mode}
        if parent_timeline_ref is not None:
            origin["parentTimelineRef"] = parent_timeline_ref
        document = {
            "schemaVersion": "1.0.0",
            "runId": run_id,
            "videoId": video_id,
            "provider": provider,
            "projectPath": str(project_path),
            "mainState": PipelineState.INTAKE.value,
            "sideState": None,
            "activeRefs": {},
            "blockers": [],
            "transitionHistory": [],
            "origin": origin,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        self._validate(document)
        atomic_write_json(self.path, document)
        return document

    def load(self):
        import json

        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LifecycleError(
                f"cannot load pipeline run {self.path}: {exc}"
            ) from exc
        self._validate(document)
        return document

    def _write(self, document, *, expected_updated_at=None):
        from .store import atomic_write_json

        current = self.load()
        if (
            expected_updated_at is not None
            and current["updatedAt"] != expected_updated_at
        ):
            raise LifecycleError("pipeline compare-and-swap failed")
        self._validate(document)
        atomic_write_json(self.path, document)
        return document

    def _history(self, current, *, actor, reason, to_main, to_side):
        timestamp = self.clock()
        return {
            "eventId": f"transition-{len(current['transitionHistory']) + 1:04d}",
            "occurredAt": timestamp,
            "actor": actor,
            "fromMainState": current["mainState"],
            "toMainState": to_main,
            "fromSideState": current["sideState"],
            "toSideState": to_side,
            "reason": reason,
        }

    def advance(
        self,
        target,
        facts,
        *,
        actor,
        reason,
        expected_updated_at=None,
        active_refs=None,
    ):
        from copy import deepcopy

        current = self.load()
        if current["sideState"] is not None:
            raise LifecycleError("side-state recovery requires explicit resume")
        next_state = transition(current["mainState"], target, facts)
        updated = deepcopy(current)
        history = self._history(
            current, actor=actor, reason=reason, to_main=next_state.value, to_side=None
        )
        updated["mainState"] = next_state.value
        updated["transitionHistory"].append(history)
        updated["updatedAt"] = history["occurredAt"]
        if active_refs is not None:
            updated["activeRefs"] = active_refs
        return self._write(updated, expected_updated_at=expected_updated_at)

    def enter_side_state(
        self, state, *, actor, reason, blockers=None, expected_updated_at=None
    ):
        from copy import deepcopy

        state = PipelineState(state)
        if state not in SIDE_STATES:
            raise LifecycleError(f"not a side state: {state.value}")
        current = self.load()
        if current["sideState"] is not None:
            raise LifecycleError("pipeline already has an active side state")
        updated = deepcopy(current)
        history = self._history(
            current,
            actor=actor,
            reason=reason,
            to_main=current["mainState"],
            to_side=state.value,
        )
        updated["sideState"] = state.value
        updated["blockers"] = list(blockers or [])
        updated["transitionHistory"].append(history)
        updated["updatedAt"] = history["occurredAt"]
        return self._write(updated, expected_updated_at=expected_updated_at)

    def resume(self, *, actor, reason, recovery_event, expected_updated_at=None):
        from copy import deepcopy

        current = self.load()
        if current["sideState"] is None:
            raise LifecycleError("pipeline is not in a recoverable side state")
        if not recovery_event:
            raise LifecycleError("resume requires an explicit recovery event")
        updated = deepcopy(current)
        history = self._history(
            current,
            actor=actor,
            reason=reason,
            to_main=current["mainState"],
            to_side=None,
        )
        updated["sideState"] = None
        updated["blockers"] = []
        updated["transitionHistory"].append(history)
        updated["updatedAt"] = history["occurredAt"]
        updated.setdefault("extensions", {})["lastRecovery"] = recovery_event
        return self._write(updated, expected_updated_at=expected_updated_at)
