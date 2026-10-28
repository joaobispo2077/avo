"""Canonical timeline application coordinator used by every command intent surface."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .bmap_service import BMapService
from .contracts import (
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .lifecycle import LifecycleError, PipelineRunStore, PipelineState, TransitionFacts
from .review import approval_is_current
from .store import now_iso, write_immutable_json
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

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CANDIDATE_TRANSITIONS = {
    "rendered": {"reviewing"},
    "reviewing": {"needs-human", "approved", "rejected"},
    "needs-human": {"approved", "rejected"},
    "approved": {"superseded"},
    "rejected": {"superseded"},
    "superseded": set(),
}


def _require_sha256(value: Any, label: str) -> str:
    result = str(value or "")
    if not _SHA256.fullmatch(result):
        raise ValueError(f"{label} requires an exact sha256")
    return result


def _hash_ref(
    value: dict[str, Any],
    *,
    id_keys: tuple[str, ...],
    hash_keys: tuple[str, ...],
    default_id: str,
) -> dict[str, str]:
    artifact_id = next(
        (str(value[key]) for key in id_keys if value.get(key)), default_id
    )
    sha256 = next((str(value[key]) for key in hash_keys if value.get(key)), "")
    if not sha256:
        sha256 = content_hash(value)
    return {
        "artifactId": artifact_id,
        "sha256": _require_sha256(sha256, artifact_id),
    }


def _binding_candidate_sha256(value: dict[str, Any]) -> str:
    candidate = value.get("candidate") or {}
    output = value.get("output") or {}
    return str(
        value.get("candidateSha256")
        or value.get("sourceSha256")
        or candidate.get("sha256")
        or output.get("sha256")
        or ""
    )


def _candidate_fingerprint(candidate: Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(candidate, (str, Path)):
        path = Path(candidate)
        if not path.is_file():
            raise ValueError(f"candidate does not exist: {path}")
        return file_fingerprint(path)
    fingerprint = dict(candidate)
    path = Path(str(fingerprint.get("locator") or ""))
    if not path.is_file():
        raise ValueError("candidate fingerprint requires existing locator bytes")
    actual = file_fingerprint(path)
    if actual["sha256"] != fingerprint.get("sha256") or actual[
        "sizeBytes"
    ] != fingerprint.get("sizeBytes"):
        raise ValueError("candidate path and fingerprint bytes differ")
    return actual


def _transcript_fingerprint(
    transcript: dict[str, Any], candidate_sha256: str
) -> dict[str, Any]:
    fingerprint = dict(transcript.get("fingerprint") or transcript)
    source_sha256 = _binding_candidate_sha256(transcript)
    if source_sha256 != candidate_sha256:
        raise ValueError("transcript is bound to another candidate")
    path = Path(str(fingerprint.get("locator") or ""))
    if not path.is_file():
        raise ValueError("transcript requires existing fingerprinted bytes")
    actual = file_fingerprint(path)
    if actual["sha256"] != fingerprint.get("sha256") or actual[
        "sizeBytes"
    ] != fingerprint.get("sizeBytes"):
        raise ValueError("transcript fingerprint is stale")
    return actual


def _adoption_document(workspace, path):
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(
        workspace.raw_dir.resolve()
    ):
        raise ValueError("delivery adoption evidence must remain inside the project")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("delivery adoption evidence must be an object")
    return document


def _adoption_reference(path, document):
    return {
        "path": str(Path(path).resolve()),
        **file_fingerprint(Path(path)),
        "contentHash": content_hash(document),
    }


def _human_archive_policy(workspace):
    project = _adoption_document(workspace, workspace.project_path)
    paths = (project.get("cleanup") or {}).get("preservePaths") or []
    roots = {(workspace.raw_dir / str(value)).resolve() for value in paths}
    if (workspace.raw_dir / "edit").resolve() not in roots:
        raise ValueError("human-final archive requires preserving all of edit")
    return _adoption_reference(workspace.project_path, project)


def _require_adoption_approval(workspace, snapshot, manifest, review, approval_path):
    from .approval_service import _source_approval_reference

    expected_path = (
        workspace.timeline_dir
        / "approvals"
        / f"{snapshot['approval']['artifactId']}.json"
    )
    if Path(approval_path).resolve() != expected_path.resolve():
        raise ValueError(
            "delivery adoption requires the native candidate approval path"
        )
    approval = _adoption_document(workspace, approval_path)
    references = (
        content_hash(approval) == snapshot["approval"]["sha256"],
        approval.get("approvalId") == snapshot["approval"]["artifactId"],
        content_hash(review) == snapshot["review"]["sha256"],
        (approval.get("review") or {}).get("contentHash") == content_hash(review),
        (approval.get("regressionResult") or {}).get("sha256")
        == snapshot["regressionResult"]["sha256"],
        (approval.get("actor") or {}).get("type") == "user",
        approval.get("decisionBasis")
        == "prior-exact-master-acceptance-and-current-native-authorization",
    )
    if not all(references) or not approval_is_current(
        approval,
        checkpoint="deliver",
        candidate_identity_hash=review["candidate"]["identityHash"],
        candidate_sha256=manifest["master"]["sha256"],
        dependency_lock_sha256=review["dependencyLockSha256"],
    ):
        raise ValueError("delivery adoption native approval is stale or incomplete")
    _require_adoption_approval_artifacts(approval, manifest)
    reference = approval.get("sourceApprovalRef")
    if not reference:
        raise ValueError("delivery adoption requires exact original creator acceptance")
    _adoption_document(workspace, reference["path"])
    source = _source_approval_reference(reference, manifest["master"]["sha256"])
    if source != reference:
        raise ValueError("delivery adoption requires exact original creator acceptance")
    return approval, source


def _require_adoption_approval_artifacts(approval, manifest):
    for key in ("review", "materialization"):
        reference = approval[key]
        if Path(reference["path"]).resolve() != Path(manifest[key]["path"]).resolve():
            raise ValueError(f"delivery adoption approval {key} path differs")
        actual = file_fingerprint(Path(reference["path"]))
        if any(actual[field] != reference[field] for field in ("sha256", "sizeBytes")):
            raise ValueError(f"delivery adoption approval {key} artifact changed")


def _adoption_regression(
    workspace, snapshot, review, materialization, approval, regression_path
):
    from .approval_service import require_candidate_regression

    external = regression_path or approval["regressionResult"].get("path")
    if external:
        reference = approval["regressionResult"]
        if (
            not reference.get("path")
            or Path(reference["path"]).resolve() != Path(external).resolve()
        ):
            raise ValueError("delivery adoption external regression path changed")
        _adoption_document(workspace, external)
        if file_fingerprint(Path(external))["sha256"] != reference.get("fileSha256"):
            raise ValueError("delivery adoption external regression artifact changed")
    result = require_candidate_regression(
        workspace,
        snapshot,
        review,
        regression_path=Path(external) if external else None,
        materialization=materialization,
    )
    if content_hash(result) != snapshot["regressionResult"]["sha256"]:
        raise ValueError("delivery adoption regression result changed")
    return result


def _require_adoption_gates(workspace, manifest, snapshot, review, materialization):
    from .approval_service import (
        require_candidate_review,
        require_current_candidate_dependencies,
    )
    from .review import evaluate_gate, validate_evidence_integrity

    dependencies = manifest["dependencies"]
    current = workspace.active_dependency_snapshot()
    if not {"cmap", "sync-map", "bmap", "tracks", "animation"}.issubset(current):
        raise ValueError("delivery adoption requires every current canonical head")
    require_current_candidate_dependencies(workspace, materialization, dependencies)
    require_candidate_review(
        review,
        checkpoint="deliver",
        candidate=Path(manifest["master"]["path"]),
        fingerprint=manifest["master"],
        dependencies=dependencies,
    )
    for checkpoint in ("motion-proof", "pre-master", "deliver"):
        arguments = {
            "candidate_identity_hash": review["candidate"]["identityHash"],
            "dependency_lock_sha256": review["dependencyLockSha256"],
        }
        validate_evidence_integrity(
            checkpoint,
            manifest["master"]["sha256"],
            dependencies,
            review["evidence"],
            **arguments,
        )
        evaluate_gate(
            checkpoint,
            manifest["master"]["sha256"],
            dependencies,
            review["evidence"],
            **arguments,
        )
    exact = (
        snapshot["state"] == "approved",
        snapshot["candidate"]["sha256"] == manifest["master"]["sha256"],
        snapshot["candidate"]["sizeBytes"] == manifest["master"]["sizeBytes"],
        snapshot["materialization"]["sha256"] == materialization["materializationHash"],
        snapshot["proofPlan"]["sha256"] == dependencies.get("proof-plan"),
        approval_is_current(
            manifest.get("approval"),
            checkpoint="deliver",
            candidate_identity_hash=review["candidate"]["identityHash"],
            candidate_sha256=manifest["master"]["sha256"],
            dependency_lock_sha256=review["dependencyLockSha256"],
        ),
    )
    if not all(exact):
        raise ValueError("delivery adoption candidate lifecycle is stale")


class TimelinePipeline:
    def __init__(self, workspace: TimelineWorkspace, *, motion_materializer=None):
        self.workspace = workspace
        self.motion_materializer = motion_materializer
        self.run_store = PipelineRunStore(workspace.pipeline_run_path)

    def materialize_motion(self, instance_id: str, *, output: Path) -> dict[str, Any]:
        if self.motion_materializer is None:
            raise ValueError("Canonical motion materializer is not configured")
        return self.motion_materializer(
            self.workspace, instance_id, output=Path(output)
        )

    def initialize(
        self,
        *,
        motion_selection: dict[str, Any] | None = None,
        request_id: str | None = None,
        new_request: bool = False,
    ) -> dict[str, Any]:
        if self.workspace.authority != "canonical" or not self.run_store.path.is_file():
            self.workspace.initialize()
        if motion_selection is not None:
            self.run_store.bind_motion_selection(
                motion_selection, request_id=request_id, new_request=new_request
            )
        return self.status()

    def status(self) -> dict[str, Any]:
        status = self.workspace.status()
        status["candidate"] = (
            self.candidate_status()
            if self.workspace.pipeline_run_path.is_file()
            else None
        )
        status["briefing"] = self.briefing_status()
        return status

    def briefing_status(self) -> dict[str, Any]:
        """Derive guidance from the sole selected-brief index, without activation."""
        from avo.direction.brief import BriefService

        service = BriefService(self.workspace.project_path)
        shown = service.show()
        stages = ("structure", "cmap", "bmap", "motion", "sound")
        contexts = (
            {stage: self.authoring_context(stage) for stage in stages}
            if shown.get("selection")
            else {}
        )
        return {**shown, "stageContexts": contexts}

    def authoring_context(self, stage: str) -> dict[str, Any]:
        """Offer selected guidance, never edit/render approval or timeline changes."""
        from avo.direction.brief import BriefService
        from avo.direction.rules import DirectionError

        service = BriefService(self.workspace.project_path)
        result = service.stage_context(
            stage, self.workspace.active_dependency_snapshot(), record=False
        )
        if result.get("context") and service.video_id != self.workspace.video_id:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Selected brief and workspace video identity differ",
            )
        return result

    @property
    def candidate_snapshots_dir(self) -> Path:
        return self.workspace.timeline_dir / "candidate-snapshots"

    def candidate_snapshot_path(self, snapshot: dict[str, Any]) -> Path:
        return (
            self.candidate_snapshots_dir
            / snapshot["candidate"]["sha256"]
            / f"{snapshot['snapshotId']}.json"
        )

    def _snapshot_by_id(self, snapshot_id: str) -> dict[str, Any]:
        matches = list(self.candidate_snapshots_dir.glob(f"*/{snapshot_id}.json"))
        if len(matches) != 1:
            raise ValueError(
                f"candidate snapshot identity is not unique: {snapshot_id}"
            )
        try:
            snapshot = json.loads(matches[0].read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"cannot load candidate snapshot {snapshot_id}: {exc}"
            ) from exc
        validate_document(snapshot, "avo.candidate-snapshot.schema.json")
        if snapshot["snapshotHash"] != document_hash_excluding(
            snapshot, "snapshotHash"
        ):
            raise ValueError(f"candidate snapshot hash is invalid: {snapshot_id}")
        return snapshot

    def active_candidate_snapshot(self) -> dict[str, Any] | None:
        run = self.run_store.load()
        reference = run["activeRefs"].get("activeCandidateSnapshot")
        if reference is None:
            return None
        snapshot = self._snapshot_by_id(str(reference["snapshotId"]))
        if snapshot["snapshotHash"] != reference["sha256"]:
            raise ValueError("active candidate snapshot reference is stale")
        return snapshot

    def candidate_status(self) -> dict[str, Any] | None:
        snapshot = self.active_candidate_snapshot()
        if snapshot is None:
            return None
        return {
            "snapshotId": snapshot["snapshotId"],
            "snapshotHash": snapshot["snapshotHash"],
            "state": snapshot["state"],
            "candidate": snapshot["candidate"],
            "iterationId": snapshot["iterationId"],
            "proofPlan": snapshot["proofPlan"],
            "materialization": snapshot["materialization"],
            "evidence": {
                "transcript": snapshot["transcript"],
                "review": snapshot["review"],
                "regressionResult": snapshot["regressionResult"],
                "approval": snapshot["approval"],
            },
        }

    def proof_build_status(
        self,
        *,
        proof_plan: dict[str, Any] | str | Path,
        media_inputs: dict[str, Any],
        microproof_gate: dict[str, Any] | str | Path | None = None,
        render_port: Any | None = None,
    ) -> dict[str, Any]:
        from .materialize import proof_build_status

        result = proof_build_status(
            workspace=self.workspace,
            proof_plan=proof_plan,
            media_inputs=media_inputs,
            microproof_gate=microproof_gate,
            render_port=render_port,
        )
        result["candidate"] = self.candidate_status()
        return result

    def render_proof_microproofs(
        self,
        *,
        proof_plan: dict[str, Any] | str | Path,
        media_inputs: dict[str, Any],
        render_port: Any | None = None,
    ) -> dict[str, Any]:
        from .materialize import render_proof_microproofs

        return render_proof_microproofs(
            workspace=self.workspace,
            proof_plan=proof_plan,
            media_inputs=media_inputs,
            render_port=render_port,
        )

    def build_proof_candidate(
        self,
        *,
        proof_plan: dict[str, Any] | str | Path,
        microproof_gate: dict[str, Any] | str | Path,
        media_inputs: dict[str, Any],
        expected_active_snapshot_hash: str | None,
        render_port: Any | None = None,
    ) -> dict[str, Any]:
        """Render only behind a current gate, then atomically activate candidate."""
        from .materialize import materialize_proof_plan
        from .proof_plan import ProofPlanCompiler

        compiler = ProofPlanCompiler(self.workspace)
        plan = (
            deepcopy(proof_plan)
            if isinstance(proof_plan, dict)
            else compiler.load(proof_plan)
        )
        materialization = materialize_proof_plan(
            workspace=self.workspace,
            proof_plan=plan,
            microproof_gate=microproof_gate,
            media_inputs=media_inputs,
            render_port=render_port,
        )
        canonical_materialization = {
            key: value for key, value in materialization.items() if key != "path"
        }
        snapshot = self.record_candidate_snapshot(
            state="rendered",
            candidate=canonical_materialization["output"],
            iteration_id=plan["iterationId"],
            proof_plan=plan,
            materialization=canonical_materialization,
            expected_active_snapshot_hash=expected_active_snapshot_hash,
        )
        return {
            "materialization": materialization,
            "candidateSnapshot": snapshot,
        }

    def _next_snapshot_id(self) -> str:
        existing = {path.stem for path in self.candidate_snapshots_dir.glob("*/*.json")}
        video = (
            re.sub(r"[^a-z0-9-]+", "-", self.workspace.video_id.lower()).strip("-")
            or "video"
        )
        if not video[0].isalpha():
            video = f"video-{video}"
        video = video[:44]
        sequence = len(existing) + 1
        while True:
            suffix = f"-candidate-{sequence:04d}"
            candidate = f"{video[: 64 - len(suffix)]}{suffix}"
            if candidate not in existing:
                return candidate
            sequence += 1

    @staticmethod
    def _validate_stage(
        state: str,
        *,
        transcript: dict[str, Any] | None,
        review: dict[str, Any] | None,
        regression_result: dict[str, Any] | None,
        approval: dict[str, Any] | None,
    ) -> None:
        values = {
            "transcript": transcript,
            "review": review,
            "regression result": regression_result,
            "approval": approval,
        }
        required = {
            "rendered": set(),
            "reviewing": {"transcript"},
            "needs-human": {"transcript", "review", "regression result"},
            "approved": {
                "transcript",
                "review",
                "regression result",
                "approval",
            },
            "rejected": {"transcript", "review", "regression result"},
            "superseded": set(),
        }
        if state not in required:
            raise ValueError(f"unsupported candidate snapshot state: {state}")
        missing = [name for name in required[state] if values[name] is None]
        if missing:
            raise ValueError(
                f"{state} candidate requires " + ", ".join(sorted(missing))
            )
        if state in {"rendered", "reviewing"}:
            allowed = required[state]
            unexpected = [
                name
                for name, value in values.items()
                if value is not None and name not in allowed
            ]
            if unexpected:
                raise ValueError(
                    f"{state} candidate cannot bind " + ", ".join(sorted(unexpected))
                )

    def record_candidate_snapshot(
        self,
        *,
        state: str,
        candidate: Path | dict[str, Any],
        iteration_id: str,
        proof_plan: dict[str, Any],
        materialization: dict[str, Any],
        expected_active_snapshot_hash: str | None,
        transcript: dict[str, Any] | None = None,
        review: dict[str, Any] | None = None,
        regression_result: dict[str, Any] | None = None,
        approval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append and atomically activate one coherent candidate lifecycle state."""
        self._validate_stage(
            state,
            transcript=transcript,
            review=review,
            regression_result=regression_result,
            approval=approval,
        )
        fingerprint = _candidate_fingerprint(candidate)
        candidate_sha256 = fingerprint["sha256"]
        if proof_plan.get("proofPlanHash") and proof_plan[
            "proofPlanHash"
        ] != document_hash_excluding(proof_plan, "proofPlanHash"):
            raise ValueError("proof plan hash is invalid")
        if materialization.get("materializationHash") and materialization[
            "materializationHash"
        ] != document_hash_excluding(materialization, "materializationHash"):
            raise ValueError("materialization hash is invalid")
        plan_ref = _hash_ref(
            proof_plan,
            id_keys=("artifactId", "proofPlanId"),
            hash_keys=("sha256", "proofPlanHash"),
            default_id="proof-plan",
        )
        materialization_ref = _hash_ref(
            materialization,
            id_keys=("artifactId", "materializationId"),
            hash_keys=("sha256", "materializationHash"),
            default_id="materialization",
        )
        if proof_plan.get("iterationId") not in {None, iteration_id}:
            raise ValueError("proof plan is bound to another iteration")
        materialized_sha256 = _binding_candidate_sha256(materialization)
        if materialized_sha256 != candidate_sha256:
            raise ValueError("materialization is bound to another candidate")
        materialized_size = (materialization.get("output") or {}).get("sizeBytes")
        if (
            materialized_size is not None
            and materialized_size != fingerprint["sizeBytes"]
        ):
            raise ValueError("materialization candidate byte size is stale")

        run = self.run_store.load()
        active_ref = run["activeRefs"].get("activeCandidateSnapshot") or {}
        if active_ref.get("sha256") != expected_active_snapshot_hash:
            raise LifecycleError("candidate snapshot compare-and-swap failed")
        active = self.active_candidate_snapshot() if active_ref else None
        core = active is not None and (
            active["candidate"]["sha256"],
            active["iterationId"],
            active["proofPlan"],
            active["materialization"],
        ) == (candidate_sha256, iteration_id, plan_ref, materialization_ref)
        if state != "rendered":
            if active is None:
                raise ValueError(
                    f"{state} candidate requires an active rendered snapshot"
                )
            if state not in _CANDIDATE_TRANSITIONS[active["state"]]:
                raise ValueError(
                    f"invalid candidate transition {active['state']} -> {state}"
                )
            if not core:
                raise ValueError(
                    "candidate transition mixes active snapshot references"
                )

        transcript_fp = (
            _transcript_fingerprint(transcript, candidate_sha256)
            if transcript is not None
            else None
        )
        review_ref = self._candidate_bound_ref(
            review,
            candidate_sha256=candidate_sha256,
            plan_sha256=plan_ref["sha256"],
            label="review",
        )
        regression_ref = self._candidate_bound_ref(
            regression_result,
            candidate_sha256=candidate_sha256,
            label="regression result",
        )
        approval_ref = self._candidate_bound_ref(
            approval,
            candidate_sha256=candidate_sha256,
            label="approval",
        )
        if active is not None and (state != "rendered" or core):
            for name, value in (
                ("transcript", transcript_fp),
                ("review", review_ref),
                ("regressionResult", regression_ref),
                ("approval", approval_ref),
            ):
                if active[name] is not None and value != active[name]:
                    raise ValueError(
                        f"candidate transition replaces exact {name} binding"
                    )

        snapshot = {
            "schemaVersion": "1.0.0",
            "snapshotId": self._next_snapshot_id(),
            "candidate": fingerprint,
            "iterationId": iteration_id,
            "proofPlan": plan_ref,
            "materialization": materialization_ref,
            "transcript": transcript_fp,
            "review": review_ref,
            "regressionResult": regression_ref,
            "approval": approval_ref,
            "state": state,
            "supersedesSnapshotId": active["snapshotId"] if active else None,
            "createdAt": now_iso(),
        }
        snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
        validate_document(snapshot, "avo.candidate-snapshot.schema.json")
        write_immutable_json(self.candidate_snapshot_path(snapshot), snapshot)
        self.run_store.activate_candidate_snapshot(
            {
                "snapshotId": snapshot["snapshotId"],
                "sha256": snapshot["snapshotHash"],
            },
            expected_active_snapshot_hash=expected_active_snapshot_hash,
            expected_updated_at=run["updatedAt"],
        )
        return snapshot

    @staticmethod
    def _candidate_bound_ref(
        value: dict[str, Any] | None,
        *,
        candidate_sha256: str,
        label: str,
        plan_sha256: str | None = None,
    ) -> dict[str, str] | None:
        if value is None:
            return None
        if _binding_candidate_sha256(value) != candidate_sha256:
            raise ValueError(f"{label} is bound to another candidate")
        declared_plan = str(
            value.get("proofPlanSha256")
            or (value.get("dependencies") or {}).get("proof-plan")
            or ""
        )
        if plan_sha256 is not None and declared_plan != plan_sha256:
            raise ValueError(f"{label} is not bound to the exact proof plan")
        return _hash_ref(
            value,
            id_keys=("artifactId", "reviewId", "approvalId", "contractId"),
            hash_keys=("sha256", "reviewHash", "approvalHash", "resultHash"),
            default_id=label.replace(" ", "-"),
        )

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

    @staticmethod
    def _bind_candidate_file(
        active_candidate: dict[str, Any] | None,
        active_refs: dict[str, Any],
        candidate: Path,
        label: str,
    ) -> None:
        if not candidate.is_file():
            raise ValueError(f"{label} requires encoded candidate")
        if active_candidate is None:
            active_refs["candidatePath"] = str(candidate)
        elif (
            file_fingerprint(candidate)["sha256"]
            != active_candidate["candidate"]["sha256"]
        ):
            raise ValueError(f"{label} candidate differs from active snapshot")

    @staticmethod
    def _bind_candidate_identity(
        active_candidate: dict[str, Any] | None,
        active_refs: dict[str, Any],
        candidate: dict[str, Any],
        *,
        prefix: str,
    ) -> None:
        if active_candidate is None:
            active_refs.update(
                {
                    f"{prefix}CandidateSha256": candidate["sha256"],
                    f"{prefix}CandidateIdentityHash": candidate["identityHash"],
                }
            )
        elif candidate["sha256"] != active_candidate["candidate"]["sha256"]:
            raise ValueError(f"{prefix} approval differs from active snapshot")

    def advance(self, stage: str, **payload: Any) -> dict[str, Any]:
        """Advance one persisted stage using canonical artifacts/evidence, never chat booleans."""
        self.initialize()
        target = _TARGETS.get(stage)
        if target is None:
            raise ValueError(f"unknown pipeline stage: {stage}")
        current = self.run_store.load()
        active_refs = dict(current["activeRefs"])
        active_candidate = self.active_candidate_snapshot()
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
            self._bind_candidate_file(
                active_candidate, active_refs, candidate, "cut AI review"
            )
        elif target == PipelineState.CMAP_APPROVED:
            facts = self._review_facts(
                payload.get("review") or {},
                payload.get("approval"),
                "cut-proof",
            )
            candidate = payload["review"]["candidate"]
            self._bind_candidate_identity(
                active_candidate, active_refs, candidate, prefix="cut"
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
            self._bind_candidate_file(
                active_candidate, active_refs, candidate, "assembly AI review"
            )
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
            self._bind_candidate_file(
                active_candidate, active_refs, candidate, "pre-master review"
            )
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
            if active_candidate is not None:
                if master["sha256"] != active_candidate["candidate"]["sha256"]:
                    raise ValueError("delivered master differs from active snapshot")
            else:
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

    def adopt_delivery(
        self,
        *,
        approval_path: Path,
        actor: str,
        reason: str,
        regression_path: Path | None = None,
    ) -> dict[str, Any]:
        """Adopt one existing approved master after a real combined final review.

        This is an explicit administrative migration. Earlier lifecycle history
        is preserved and no earlier checkpoint execution is invented.
        """
        from .delivery import DeliveryService

        current = self.run_store.load()
        if current["sideState"] is not None:
            raise LifecycleError(
                "delivery adoption requires explicit side-state recovery"
            )
        service = DeliveryService(self.workspace)
        manifest = service.validate_current()
        if (
            manifest.get("state") != "delivered"
            or manifest.get("adoption", {}).get("mode") != "existing-master"
        ):
            raise ValueError(
                "delivery adoption requires a delivered existing-master manifest"
            )
        snapshot = self.active_candidate_snapshot()
        if snapshot is None or snapshot["state"] != "approved":
            raise ValueError("delivery adoption requires the active approved candidate")
        review_path = Path(manifest["review"]["path"])
        review = _adoption_document(self.workspace, review_path)
        validate_document(review, "avo.review-evidence.schema.json")
        materialization = _adoption_document(
            self.workspace, manifest["materialization"]["path"]
        )
        _require_adoption_gates(
            self.workspace, manifest, snapshot, review, materialization
        )
        approval, source = _require_adoption_approval(
            self.workspace, snapshot, manifest, review, approval_path
        )
        _adoption_regression(
            self.workspace, snapshot, review, materialization, approval, regression_path
        )
        identity = {
            "mode": "existing-approved-master",
            "scope": "current-union-gates-and-existing-creator-acceptance; no-historical-stage-backfill",
            "candidateSnapshot": {
                "snapshotId": snapshot["snapshotId"],
                "sha256": snapshot["snapshotHash"],
            },
            "candidateSha256": manifest["master"]["sha256"],
            "candidateSizeBytes": manifest["master"]["sizeBytes"],
            "proofPlan": snapshot["proofPlan"],
            "materialization": snapshot["materialization"],
            "review": _adoption_reference(review_path, review),
            "approval": _adoption_reference(approval_path, approval),
            "sourceApprovalRef": source,
            "deliveryManifest": _adoption_reference(service.manifest_path, manifest),
            "dependencyLockSha256": review["dependencyLockSha256"],
            "dependencies": manifest["dependencies"],
            "verifiedCheckpointPolicies": ["motion-proof", "pre-master", "deliver"],
        }
        active_refs = dict(current["activeRefs"])
        for name in ("cmap", "sync-map", "bmap", "tracks", "animation"):
            prefix = "sync" if name == "sync-map" else name
            active_refs[f"{prefix}RevisionId"] = self.workspace.require_active(name)[
                "headRevisionId"
            ]
        active_refs["masterSha256"] = manifest["master"]["sha256"]
        return self.run_store.adopt_delivery(
            identity,
            actor=actor,
            reason=reason,
            active_refs=active_refs,
            expected_updated_at=current["updatedAt"],
        )

    def adopt_human_final_delivery(
        self,
        *,
        human_final_disposition_path: Path,
        actor: str,
        reason: str,
        archive: bool = False,
    ) -> dict[str, Any]:
        """Adopt explicit human authority while preserving failed/incomplete automation."""
        from .approval_service import require_human_final_disposition
        from .delivery import DeliveryService

        current = self.run_store.load()
        if current["sideState"] is not None:
            raise LifecycleError(
                "human-final adoption requires explicit side-state recovery"
            )
        policy = _human_archive_policy(self.workspace) if archive else None
        service = DeliveryService(self.workspace)
        manifest = service.validate_current()
        reference = manifest.get("adoption", {}).get("humanFinalDisposition")
        if manifest.get("state") != "delivered" or not reference:
            raise ValueError("human-final adoption requires its delivered manifest")
        if (
            Path(reference["path"]).resolve()
            != Path(human_final_disposition_path).resolve()
        ):
            raise ValueError("human-final delivery disposition path differs")
        materialization = _adoption_document(
            self.workspace, manifest["materialization"]["path"]
        )
        disposition = require_human_final_disposition(
            self.workspace,
            human_final_disposition_path,
            candidate=Path(manifest["master"]["path"]),
            fingerprint=manifest["master"],
            materialization=materialization,
            dependencies=manifest["dependencies"],
        )
        disposition_ref = _adoption_reference(human_final_disposition_path, disposition)
        prior = (
            (current.get("extensions") or {})
            .get("deliveryAdoption", {})
            .get("identity", {})
        )
        identity = {
            "mode": "existing-approved-master",
            "authority": "human-final",
            "scope": "explicit-human-final-authority; automated-outcomes-retained; no-historical-stage-backfill",
            "priorCandidateSnapshot": prior.get(
                "priorCandidateSnapshot",
                current["activeRefs"].get("activeCandidateSnapshot"),
            ),
            "candidateSha256": manifest["master"]["sha256"],
            "candidateSizeBytes": manifest["master"]["sizeBytes"],
            "humanFinalDisposition": disposition_ref,
            "deliveryManifest": _adoption_reference(service.manifest_path, manifest),
            "dependencies": manifest["dependencies"],
            "dependencyLockSha256": disposition["dependencyLockSha256"],
            "automatedGatePassAsserted": False,
            "regressionPassAsserted": False,
        }
        active = dict(current["activeRefs"])
        active.pop("activeCandidateSnapshot", None)
        for name in ("cmap", "sync-map", "bmap", "tracks", "animation"):
            prefix = "sync" if name == "sync-map" else name
            active[f"{prefix}RevisionId"] = self.workspace.require_active(name)[
                "headRevisionId"
            ]
        active["masterSha256"] = manifest["master"]["sha256"]
        active["humanFinalDisposition"] = disposition_ref
        result = self.run_store.adopt_delivery(
            identity,
            actor=actor,
            reason=reason,
            active_refs=active,
            expected_updated_at=current["updatedAt"],
        )
        if archive:
            return self.run_store.archive_human_final_delivery(
                disposition_ref,
                policy,
                actor=actor,
                reason=reason,
                expected_updated_at=result["updatedAt"],
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
