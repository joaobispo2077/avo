"""Canonical AVO pipeline state machine and transition guards."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .store import serialized_timeline


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


def _require_adoption_candidate(current, adoption, active_refs):
    if adoption.get("authority") == "human-final":
        expected = adoption.get("priorCandidateSnapshot")
        if active_refs.get("activeCandidateSnapshot") is not None:
            raise LifecycleError(
                "human-final adoption cannot retain a stale active snapshot"
            )
    else:
        expected = adoption["candidateSnapshot"]
    if current["activeRefs"].get("activeCandidateSnapshot") != expected:
        raise LifecycleError("delivery adoption candidate snapshot is stale")


def _require_human_archive_adoption(current, disposition):
    adoption = (
        (current.get("extensions") or {})
        .get("deliveryAdoption", {})
        .get("identity", {})
    )
    if (
        current["mainState"] != PipelineState.DELIVERED.value
        or current["sideState"] is not None
        or adoption.get("authority") != "human-final"
        or adoption.get("humanFinalDisposition") != disposition
    ):
        raise LifecycleError(
            "human-final archive requires its exact delivered disposition"
        )


def _validate_motion_request(selection, request_id, new_request):
    from .contracts import ContractError, validate_document

    try:
        validate_document(selection, "avo.motion.schema.json#/$defs/selection")
    except ContractError as exc:
        raise LifecycleError(f"invalid motion selection: {exc}") from exc
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id.strip()
    ):
        raise LifecycleError("motion request identity must be a nonempty string")
    if type(new_request) is not bool:
        raise LifecycleError("new_request must be a boolean")


def _motion_requests(document):
    choices = list((document.get("extensions") or {}).get("motionRequestHistory", []))
    choice = (document.get("executionChoices") or {}).get("motion")
    if choice is not None:
        choices.append(choice)
    return choices


def _known_motion_request(document, request_id):
    return next(
        (
            choice
            for choice in _motion_requests(document)
            if choice["requestId"] == request_id
        ),
        None,
    )


def _require_import_hashes(values):
    import re

    if any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for value in values
    ):
        raise LifecycleError("import draft selection requires exact sha256 identities")


def _require_import_text(values):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise LifecycleError(
            "import draft selection requires revision identities, actor and reason"
        )


def _require_import_inventory(inventory):
    if not isinstance(inventory, dict):
        raise LifecycleError("import draft requires current source inventory")
    sources = inventory.get("sources")
    if not isinstance(sources, list) or not sources:
        raise LifecycleError("import draft requires current source inventory")
    if any(
        not isinstance(source, dict)
        or not isinstance(source.get("sourceId"), str)
        or not source["sourceId"].strip()
        for source in sources
    ):
        raise LifecycleError("import source inventory requires source identities")


def _require_import_refs(active_refs, revision_id, revision_hash):
    required = {
        "rawInventory",
        "syncRevisionId",
        "syncRevisionHash",
        "cmapRevisionId",
        "cmapRevisionHash",
    }
    if not isinstance(active_refs, dict) or set(active_refs) != required:
        raise LifecycleError(
            "import draft refs must contain only current source, Sync and CMap refs"
        )
    if (active_refs["cmapRevisionId"], active_refs["cmapRevisionHash"]) != (
        revision_id,
        revision_hash,
    ):
        raise LifecycleError(
            "import draft refs do not match the committed CMap identity"
        )
    _require_import_hashes((active_refs["syncRevisionHash"],))
    _require_import_text((active_refs["syncRevisionId"],))
    _require_import_inventory(active_refs["rawInventory"])


def _import_draft_selections(document):
    extensions = document.get("extensions") or {}
    history = extensions.get("importDraftSelectionHistory", [])
    if not isinstance(history, list) or any(
        not isinstance(item, dict) for item in history
    ):
        raise LifecycleError("import draft selection history is invalid")
    latest = extensions.get("importDraftSelection")
    if latest is not None:
        if not isinstance(latest, dict):
            raise LifecycleError("import draft selection identity is invalid")
        history = [*history, latest]
    return history


def _known_import_draft_selection(document, identity):
    matches = [
        item
        for item in _import_draft_selections(document)
        if item.get("activationId") == identity["activationId"]
    ]
    if any(item != identity for item in matches):
        raise LifecycleError(
            "import draft selection identity conflicts with its recorded activation"
        )
    return bool(matches)


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
        for choice in _motion_requests(document):
            if choice["runId"] != document["runId"]:
                raise LifecycleError(
                    "motion execution choice belongs to a different run"
                )
            if not choice["requestId"].strip():
                raise LifecycleError(
                    "motion execution choice requires a request identity"
                )

    @serialized_timeline(lambda self: self.path.parent)
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

    @serialized_timeline(lambda self: self.path.parent)
    def bind_motion_selection(self, selection, *, request_id=None, new_request=False):
        """Pin authoring intent for one request without changing editorial state."""
        from copy import deepcopy
        from uuid import uuid4

        _validate_motion_request(selection, request_id, new_request)
        current = self.load()
        previous = (current.get("executionChoices") or {}).get("motion")
        requested = {
            "runId": current["runId"],
            "requestId": request_id or f"motion-{uuid4().hex}",
            **{key: selection[key] for key in ("engine", "source", "resolutionHash")},
        }
        known = _known_motion_request(current, request_id)
        if known is not None:
            if requested != known:
                raise LifecycleError(
                    "motion request identity conflicts with its recorded selection"
                )
            return current
        if previous is not None and not new_request:
            if request_id is not None:
                raise LifecycleError(
                    "a different motion request identity requires new_request=True"
                )
            return current
        updated = deepcopy(current)
        if previous is not None:
            updated.setdefault("extensions", {}).setdefault(
                "motionRequestHistory", []
            ).append(deepcopy(previous))
        updated.setdefault("executionChoices", {})["motion"] = requested
        updated["updatedAt"] = self.clock()
        return self._write(updated, expected_updated_at=current["updatedAt"])

    @serialized_timeline(lambda self: self.path.parent)
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

    @serialized_timeline(lambda self: self.path.parent)
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

    @serialized_timeline(lambda self: self.path.parent)
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

    @serialized_timeline(lambda self: self.path.parent)
    def adopt_delivery(
        self,
        adoption,
        *,
        actor,
        reason,
        active_refs,
        expected_updated_at=None,
    ):
        """Record one verified administrative migration, never backfill stage passes."""
        from copy import deepcopy

        from .contracts import content_hash

        current = self.load()
        if current["sideState"] is not None:
            raise LifecycleError(
                "delivery adoption requires explicit side-state recovery"
            )
        if not actor.strip() or not reason.strip():
            raise LifecycleError("delivery adoption requires an actor and reason")
        digest = content_hash(adoption)
        existing = (current.get("extensions") or {}).get("deliveryAdoption")
        if existing is not None:
            if existing["adoptionHash"] == digest and current["mainState"] in {
                PipelineState.DELIVERED.value,
                PipelineState.ARCHIVED.value,
            }:
                return current
            raise LifecycleError("existing delivery adoption identity cannot change")
        if current["mainState"] in {
            PipelineState.DELIVERED.value,
            PipelineState.ARCHIVED.value,
        }:
            raise LifecycleError("delivered lifecycle has no matching adoption")
        _require_adoption_candidate(current, adoption, active_refs)
        updated = deepcopy(current)
        history = self._history(
            current,
            actor=actor,
            reason=f"administrative existing-master adoption: {reason}",
            to_main=PipelineState.DELIVERED.value,
            to_side=None,
        )
        updated["mainState"] = PipelineState.DELIVERED.value
        updated["activeRefs"] = deepcopy(active_refs)
        updated["transitionHistory"].append(history)
        updated["updatedAt"] = history["occurredAt"]
        updated.setdefault("extensions", {})["deliveryAdoption"] = {
            "adoptionHash": digest,
            "registeredAt": history["occurredAt"],
            "identity": deepcopy(adoption),
        }
        return self._write(updated, expected_updated_at=expected_updated_at)

    @serialized_timeline(lambda self: self.path.parent)
    def archive_human_final_delivery(
        self, disposition, retention_policy, *, actor, reason, expected_updated_at=None
    ):
        """Record the explicit human archive decision, not byte verification or cleanup."""
        from copy import deepcopy

        current = self.load()
        identity = {
            "authority": "human-final",
            "humanFinalDisposition": disposition,
            "retentionPolicy": retention_policy,
            "cleanupExecuted": False,
            "preservationVerification": "recorded-separately-in-final-preservation-receipt",
            "preservationReceiptPath": "edit/cleanup/preservation-result.json",
            "byteVerificationAsserted": False,
        }
        existing = (current.get("extensions") or {}).get("humanFinalArchive")
        if (
            current["mainState"] == PipelineState.ARCHIVED.value
            and existing == identity
        ):
            return current
        _require_human_archive_adoption(current, disposition)
        if not actor.strip() or not reason.strip():
            raise LifecycleError("human-final archive requires an actor and reason")
        updated = deepcopy(current)
        history = self._history(
            current,
            actor=actor,
            reason=f"human-final preserve-all archive decision: {reason}",
            to_main=PipelineState.ARCHIVED.value,
            to_side=None,
        )
        updated["mainState"] = PipelineState.ARCHIVED.value
        updated["transitionHistory"].append(history)
        updated["updatedAt"] = history["occurredAt"]
        updated.setdefault("extensions", {})["humanFinalArchive"] = identity
        return self._write(updated, expected_updated_at=expected_updated_at)

    @serialized_timeline(lambda self: self.path.parent)
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

    @serialized_timeline(lambda self: self.path.parent)
    def reconcile_import_draft(
        self,
        *,
        activation_id,
        cmap_revision_id,
        cmap_revision_hash,
        active_refs,
        actor,
        reason,
    ):
        """Reconcile an explicitly committed import, never resurrect prior approvals.

        The caller verifies the canonical commit and current Sync. An exact retry
        is a no-op even after later review progress or another import selection.
        """
        from copy import deepcopy

        from .contracts import content_hash

        _require_import_hashes((activation_id, cmap_revision_hash))
        _require_import_text((cmap_revision_id, actor, reason))
        _require_import_refs(active_refs, cmap_revision_id, cmap_revision_hash)
        identity = {
            "activationId": activation_id,
            "cmapRevisionId": cmap_revision_id,
            "cmapRevisionHash": cmap_revision_hash,
            "activeRefsHash": content_hash(active_refs),
        }
        current = self.load()
        if _known_import_draft_selection(current, identity):
            return current
        updated = deepcopy(current)
        history = self._history(
            current,
            actor=actor,
            reason=reason,
            to_main=PipelineState.CMAP_DRAFT.value,
            to_side=None,
        )
        updated.update(
            mainState=PipelineState.CMAP_DRAFT.value,
            sideState=None,
            blockers=[],
            activeRefs=deepcopy(active_refs),
            updatedAt=history["occurredAt"],
        )
        updated["transitionHistory"].append(history)
        extensions = updated.setdefault("extensions", {})
        previous = extensions.get("importDraftSelection")
        if previous is not None:
            extensions.setdefault("importDraftSelectionHistory", []).append(
                deepcopy(previous)
            )
        extensions["importDraftSelection"] = identity
        return self._write(updated, expected_updated_at=current["updatedAt"])

    @serialized_timeline(lambda self: self.path.parent)
    def bind_cutting_context(self, references, *, expected_updated_at=None):
        """Bind evidence without changing state or granting editorial approval."""
        from copy import deepcopy

        from .contracts import ContractError, validate_document

        if not isinstance(references, dict):
            raise LifecycleError("cutting references must be an object")
        allowed = {"analysis", "proposal", "verification", "repairLedger", "decisions"}
        if set(references) - allowed:
            raise LifecycleError("unknown cutting reference role")
        try:
            for reference in references.values():
                validate_document(
                    reference, "avo.cutting.schema.json#/$defs/artifactRef"
                )
        except ContractError as exc:
            raise LifecycleError(f"invalid cutting reference: {exc}") from exc
        current = self.load()
        updated = deepcopy(current)
        updated["activeRefs"]["cutting"] = {
            **updated["activeRefs"].get("cutting", {}),
            **deepcopy(references),
        }
        updated["updatedAt"] = self.clock()
        return self._write(updated, expected_updated_at=expected_updated_at)

    @serialized_timeline(lambda self: self.path.parent)
    def bind_iteration_context(
        self,
        *,
        ledger_revision_id,
        ledger_sha256,
        regression_contract_id,
        regression_contract_sha256,
        expected_updated_at=None,
    ):
        """Atomically bind active lightweight iteration and regression history."""
        import re
        from copy import deepcopy

        exact_sha = re.compile(r"^[a-f0-9]{64}$")
        if (
            not str(ledger_revision_id).strip()
            or not str(regression_contract_id).strip()
        ):
            raise LifecycleError("iteration context identities are required")
        if not exact_sha.fullmatch(str(ledger_sha256)) or not exact_sha.fullmatch(
            str(regression_contract_sha256)
        ):
            raise LifecycleError("iteration context requires exact sha256 values")
        current = self.load()
        updated = deepcopy(current)
        updated["activeRefs"]["iterationLedger"] = {
            "revisionId": str(ledger_revision_id),
            "sha256": str(ledger_sha256),
        }
        updated["activeRefs"]["regressionContract"] = {
            "contractId": str(regression_contract_id),
            "sha256": str(regression_contract_sha256),
        }
        updated["updatedAt"] = self.clock()
        return self._write(updated, expected_updated_at=expected_updated_at)

    @serialized_timeline(lambda self: self.path.parent)
    def activate_candidate_snapshot(
        self,
        reference,
        *,
        expected_active_snapshot_hash,
        expected_updated_at=None,
    ):
        """Atomically replace every loose candidate ref with one snapshot ref."""
        from copy import deepcopy

        current = self.load()
        active = current["activeRefs"].get("activeCandidateSnapshot") or {}
        if active.get("sha256") != expected_active_snapshot_hash:
            raise LifecycleError("candidate snapshot compare-and-swap failed")
        updated = deepcopy(current)
        stale = {
            "candidatePath",
            "candidateSha256",
            "candidateIdentityHash",
            "cutCandidateSha256",
            "cutCandidateIdentityHash",
            "transcript",
            "materialization",
            "review",
            "reviewIdentityHash",
            "regressionResult",
            "approval",
            "masterSha256",
        }
        for key in stale:
            updated["activeRefs"].pop(key, None)
        updated["activeRefs"]["activeCandidateSnapshot"] = dict(reference)
        updated["updatedAt"] = self.clock()
        return self._write(
            updated,
            expected_updated_at=expected_updated_at or current["updatedAt"],
        )
