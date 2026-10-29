"""Exact creator decisions bound to current review, materialization, and CMap lineage."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import (
    content_hash,
    dependency_lock_hash,
    file_fingerprint,
    validate_document,
)
from .lifecycle import PipelineRunStore, PipelineState, TransitionFacts
from .review import GateError, evaluate_gate, validate_evidence_integrity
from .store import now_iso, write_immutable_json
from .workspace import TimelineWorkspace

_CANONICAL_HASH_ALIASES = {
    "cmap": "cmapRevisionHash",
    "sync-map": "syncRevisionHash",
    "bmap": "bmapRevisionHash",
    "tracks": "tracksRevisionHash",
}


def _locked_canonical_hash(lock, name):
    alias = _CANONICAL_HASH_ALIASES.get(name, name)
    values = {lock[key] for key in {name, alias} if key in lock}
    if len(values) > 1:
        raise ValueError(f"proof-plan canonical aliases conflict: {name}")
    return next(iter(values), None)


def _require_native_hashes(required):
    for value in required.values():
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(
                "native cut materialization dependency hashes are incomplete"
            )
        if any(c not in "0123456789abcdef" for c in value):
            raise ValueError(
                "native cut materialization dependency hashes are incomplete"
            )


def _native_raw_dependency(lock, proof_plan_id):
    sources = {key: value for key, value in lock.items() if key.startswith("source:")}
    if (
        not sources
        or re.fullmatch(r"proof-plan-[0-9a-f]{12}", str(proof_plan_id)) is None
    ):
        raise ValueError("native cut materialization source/plan identity is missing")
    _require_native_hashes(sources)
    return content_hash(sources)


def native_cut_dependencies(materialization: dict[str, Any]) -> dict[str, str]:
    """Bind an explicit initial-cut native materialization to its exact proof."""
    if (
        materialization.get("kind") != "proof-plan"
        or materialization.get("checkpoint") != "cut-proof"
    ):
        raise ValueError(
            "native cut materialization requires explicit cut-proof checkpoint"
        )
    body = {k: v for k, v in materialization.items() if k != "materializationHash"}
    if materialization.get("materializationHash") != content_hash(body):
        raise ValueError("native cut materialization record hash mismatch")
    lock = materialization.get("canonicalInputLock") or {}
    required = {
        "cmap": lock.get("cmap"),
        "sync-map": lock.get("sync-map"),
        "materialization": materialization.get("materializationHash"),
        "proof-plan": materialization.get("proofPlanHash"),
        "microproof-gate": materialization.get("microproofGateHash"),
        "cutOutput": (materialization.get("output") or {}).get("sha256"),
    }
    _require_native_hashes(required)
    return {
        **required,
        "raw": _native_raw_dependency(lock, materialization.get("proofPlanId")),
    }


def _require_native_sync(workspace, expected):
    event = workspace.store("sync-map").effective_approval()
    if event is None or event["subject"]["contentSha256"] != expected:
        raise ValueError("current approved Sync/N/A is missing or stale")


def _require_native_plan_binding(materialization, plan):
    seed = {
        key: value
        for key, value in plan.items()
        if key not in {"proofPlanId", "proofPlanHash"}
    }
    if plan["proofPlanId"] != f"proof-plan-{content_hash(seed)[:12]}":
        raise ValueError("native cut proof plan identity does not match its graph")
    for field in (
        "proofPlanId",
        "proofPlanHash",
        "checkpoint",
        "canonicalInputLock",
        "renderProfile",
    ):
        if materialization.get(field) != plan.get(field):
            raise ValueError(
                f"native cut materialization {field} differs from proof plan"
            )


def require_native_cut_materialization(workspace, materialization, candidate):
    """Verify native source-only lineage without requiring a legacy projection."""
    from .proof_plan import ProofPlanCompiler

    dependencies = native_cut_dependencies(materialization)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.load(compiler.path(materialization["proofPlanId"]))
    _require_native_plan_binding(materialization, plan)
    actual = file_fingerprint(Path(candidate))
    declared = materialization["output"]
    if (
        actual["sha256"] != declared["sha256"]
        or actual["sizeBytes"] != declared["sizeBytes"]
    ):
        raise ValueError("native cut candidate bytes differ from materialization")
    if Path(candidate).resolve() != Path(plan["output"]["path"]).resolve():
        raise ValueError("native cut candidate path differs from proof plan")
    if Path(declared["locator"]).resolve() != Path(candidate).resolve():
        raise ValueError("native cut output locator differs from candidate")
    _require_native_proof_gate(workspace, materialization, plan)
    _require_native_sync(workspace, dependencies["sync-map"])
    return dependencies


def _native_proof_lock(materialization):
    if materialization.get("kind") != "proof-plan" or materialization.get(
        "checkpoint"
    ) not in {"motion-proof", "pre-master", "deliver"}:
        raise ValueError("native proof materialization checkpoint is invalid")
    body = {k: v for k, v in materialization.items() if k != "materializationHash"}
    if materialization.get("materializationHash") != content_hash(body):
        raise ValueError("native proof materialization record hash mismatch")
    lock = materialization.get("canonicalInputLock")
    if not isinstance(lock, dict):
        raise ValueError("native proof canonical input lock is missing")
    return lock


def native_proof_dependencies(materialization: dict[str, Any]) -> dict[str, str]:
    """Derive exact review/delivery inputs from a persisted native proof record."""
    if materialization.get("checkpoint") == "cut-proof":
        return native_cut_dependencies(materialization)
    lock = _native_proof_lock(materialization)
    canonical = {
        name: _locked_canonical_hash(lock, name)
        for name in ("cmap", "sync-map", "bmap", "tracks", "animation")
    }
    dependencies = {
        key: value
        for key, value in lock.items()
        if key not in set(_CANONICAL_HASH_ALIASES.values())
    }
    dependencies.update(canonical)
    dependencies.update(
        {
            "materialization": materialization.get("materializationHash"),
            "proof-plan": materialization.get("proofPlanHash"),
            "preflight": materialization.get("preflightHash"),
            "microproof-gate": materialization.get("microproofGateHash"),
            "assembly-output": (materialization.get("output") or {}).get("sha256"),
        }
    )
    _require_native_hashes(dependencies)
    dependencies["raw"] = _native_raw_dependency(
        lock, materialization.get("proofPlanId")
    )
    return dict(sorted(dependencies.items()))


def _require_native_proof_gate(workspace, materialization, plan):
    from .materialize import (
        _load_microproof_gate,
        _require_current_microproof_gate,
        canonical_proof_media_inputs,
        default_proof_readiness,
    )
    from .proof_plan import ProofPlanCompiler

    preflight = ProofPlanCompiler(workspace).require_preflight(
        plan,
        media_inputs=canonical_proof_media_inputs(workspace, plan),
        tool_readiness=default_proof_readiness(plan, workspace=workspace),
    )
    if preflight["reportHash"] != materialization.get("preflightHash"):
        raise ValueError("native proof materialization preflight is stale")
    path = (
        Path(workspace.timeline_dir)
        / "microproofs"
        / plan["proofPlanId"]
        / f"gate-{materialization['microproofGateHash'][:12]}.json"
    )
    gate = _load_microproof_gate(path)
    if (
        gate.get("gateHash") != materialization["microproofGateHash"]
        or gate.get("proofPlanId") != plan["proofPlanId"]
    ):
        raise ValueError("native proof microproof gate identity differs")
    _require_current_microproof_gate(plan, gate, preflight_hash=preflight["reportHash"])


def require_native_proof_materialization(workspace, materialization, candidate):
    """Verify frozen native lineage, current original inputs and microproofs."""
    if materialization.get("checkpoint") == "cut-proof":
        return require_native_cut_materialization(workspace, materialization, candidate)
    from .proof_plan import ProofPlanCompiler

    dependencies = native_proof_dependencies(materialization)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.load(compiler.path(materialization["proofPlanId"]))
    _require_native_plan_binding(materialization, plan)
    candidate = Path(candidate).resolve()
    if not candidate.is_relative_to(Path(workspace.raw_dir).resolve()):
        raise ValueError("native proof candidate is outside the project")
    actual = file_fingerprint(candidate)
    declared = materialization["output"]
    if any(actual[key] != declared.get(key) for key in ("sha256", "sizeBytes")):
        raise ValueError("native proof candidate bytes differ from materialization")
    if Path(declared["locator"]).resolve() != Path(plan["output"]["path"]).resolve():
        raise ValueError("native proof output locator differs from frozen plan")
    require_current_candidate_dependencies(workspace, materialization, dependencies)
    _require_native_proof_gate(workspace, materialization, plan)
    return dependencies


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


def _automated_watch_evidence(review: dict[str, Any]) -> dict[str, Any]:
    watch = next(
        (item for item in review.get("evidence") or [] if item.get("kind") == "watch"),
        None,
    )
    if watch is None:
        raise ValueError("approval requires native automated visual review evidence")
    return watch


def _require_open_automated_status(watch: dict[str, Any]) -> None:
    manifest = watch.get("visionCoverageManifest")
    if not isinstance(manifest, dict):
        raise ValueError("approval requires a structured vision coverage manifest")
    status = str(manifest.get("aggregateStatus") or "blocked")
    if status not in {"pass", "needs-human-judgment"}:
        raise ValueError(
            "human approval is closed while automated review is blocked or failed"
        )
    contract_hash = str(manifest.get("reviewContractHash") or "")
    if contract_hash != str(
        (watch.get("policy") or {}).get("reviewContractHash") or ""
    ):
        raise ValueError("automated review contract is stale or inconsistent")


def _require_complete_frame_coverage(watch: dict[str, Any]) -> None:
    coverage = watch.get("coverage") or {}
    requested = set(coverage.get("requestedFrames") or [])
    decoded = set(coverage.get("decodedFrames") or [])
    observed = set(coverage.get("observedFrames") or [])
    if (
        not requested
        or not requested.issubset(decoded)
        or not requested.issubset(observed)
        or coverage.get("failedFrames")
        or coverage.get("coverageHoles")
    ):
        raise ValueError("automated visual review coverage is incomplete")


def _require_complete_automated_review(review: dict[str, Any]) -> None:
    watch = _automated_watch_evidence(review)
    _require_open_automated_status(watch)
    _require_complete_frame_coverage(watch)


def require_candidate_review(
    review: dict[str, Any],
    *,
    checkpoint: str,
    candidate: Path,
    fingerprint: dict[str, Any],
    dependencies: dict[str, str],
) -> None:
    """Validate persisted non-cut review identity, real coverage and artifact bytes."""
    validate_document(review, "avo.review-evidence.schema.json")
    identity = review["candidate"]
    expected_identity = content_hash(
        {
            "candidate": fingerprint["sha256"],
            "byteSize": fingerprint["sizeBytes"],
            "dependencies": dict(sorted(dependencies.items())),
            "renderProfile": "master",
        }
    )
    exact = (
        review["checkpoint"] == checkpoint,
        review["state"] == "ai-passed",
        not review.get("unresolvedRisks"),
        identity["sha256"] == fingerprint["sha256"],
        identity["byteSize"] == fingerprint["sizeBytes"],
        Path(identity["path"]).resolve() == candidate.resolve(),
        identity["renderProfile"] == "master",
        identity["dependencies"] == dependencies,
        identity["identityHash"] == expected_identity,
        review["dependencyLockSha256"] == dependency_lock_hash(dependencies),
    )
    if not all(exact):
        raise ValueError("candidate review identity or state is stale")
    try:
        evaluate_gate(
            checkpoint,
            fingerprint["sha256"],
            dependencies,
            review["evidence"],
            candidate_identity_hash=expected_identity,
            dependency_lock_sha256=review["dependencyLockSha256"],
        )
    except GateError as error:
        raise ValueError(str(error)) from error
    _require_complete_automated_review(review)
    for evidence in review["evidence"]:
        artifacts = list(evidence.get("artifacts") or [])
        vision = evidence.get("visionCoverageManifest")
        if vision:
            artifacts.append(vision["artifact"])
        for artifact in artifacts:
            if file_fingerprint(Path(artifact["path"]))["sha256"] != artifact["sha256"]:
                raise ValueError("candidate review artifact changed")


def _native_candidate_materialization(workspace, review, materialization):
    if materialization.get("checkpoint") == "cut-proof":
        raise ValueError("candidate approval requires a later native checkpoint")
    candidate = Path(review["candidate"]["path"]).resolve()
    expected = require_native_proof_materialization(
        workspace, materialization, candidate
    )
    if review["candidate"]["dependencies"] != expected:
        raise ValueError("native candidate review dependencies are not exact")
    return candidate, file_fingerprint(candidate)


def _candidate_materialization(
    workspace: TimelineWorkspace,
    review: dict[str, Any],
    materialization: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if materialization.get("kind") == "proof-plan":
        return _native_candidate_materialization(workspace, review, materialization)
    body = dict(materialization)
    body.pop("materializationHash", None)
    if materialization.get("kind") != "assembly" or materialization.get(
        "materializationHash"
    ) != content_hash(body):
        raise ValueError(
            "candidate approval requires exact canonical assembly materialization"
        )
    candidate = Path(review["candidate"]["path"]).resolve()
    if not candidate.is_relative_to(workspace.raw_dir.resolve()):
        raise ValueError("candidate approval media is outside the project")
    fingerprint = file_fingerprint(candidate)
    output = materialization.get("output") or {}
    if any(fingerprint[key] != output.get(key) for key in ("sha256", "sizeBytes")):
        raise ValueError("candidate bytes differ from assembly materialization")
    dependencies = review["candidate"]["dependencies"]
    require_current_candidate_dependencies(workspace, materialization, dependencies)
    references = {
        "materialization": materialization["materializationHash"],
        "delivery-fidelity-policy": materialization.get("deliveryFidelityPolicyHash"),
        "picture-lineage": materialization.get("pictureLineageHash"),
        "assembly-output": fingerprint["sha256"],
    }
    dependency_lock_hash(references)
    if any(dependencies.get(key) != value for key, value in references.items()):
        raise ValueError("candidate review materialization dependencies are stale")
    return candidate, fingerprint


def require_current_candidate_dependencies(workspace, materialization, dependencies):
    """Require valid current heads and the assembly's exact locked inputs."""
    current = workspace.active_dependency_snapshot()
    lock = materialization.get("canonicalInputLock") or {}
    if not {"cmap", "sync-map"}.issubset(current):
        raise ValueError("candidate approval requires current canonical heads")
    for name, digest in current.items():
        workspace.require_active(name)
        locked = _locked_canonical_hash(lock, name)
        if dependencies.get(name) != digest or (
            name in _CANONICAL_HASH_ALIASES and locked != digest
        ):
            raise ValueError(f"candidate canonical dependency is stale: {name}")


def _candidate_regression(review: dict[str, Any], path: Path | None) -> dict[str, Any]:
    results = [
        item["regressionResult"]
        for item in review["evidence"]
        if item.get("regressionResult")
    ]
    if path is not None:
        results.append(ApprovalService._load(path))
    if not results or any(item != results[0] for item in results):
        raise ValueError(
            "candidate approval requires one exact concrete regression result"
        )
    result = results[0]
    validate_document(result, "avo.review-evidence.schema.json#/$defs/regressionResult")
    if result["candidateSha256"] != review["candidate"]["sha256"]:
        raise ValueError("regression result is bound to another candidate")
    for item in result["results"]:
        if item["status"] in {"regressed", "unresolved"}:
            raise ValueError("candidate regression remains unresolved or regressed")
        _require_regression_artifacts(item["evidenceRefs"])
    return result


def _merge_review_source_bindings(lock, dependencies, expected):
    for key, digest in dependencies.items():
        if key.startswith("source:"):
            if key in expected and expected[key] != digest:
                raise ValueError(f"proof-plan source aliases conflict: {key}")
            expected[key] = digest
            if key not in lock:
                raise ValueError(f"proof-plan source review binding is missing: {key}")


def _review_raw_fingerprints(dependencies, materialization):
    assembly_lock = (materialization or {}).get("canonicalInputLock") or {}
    raw = assembly_lock.get("rawFingerprints")
    if "raw" in dependencies and (
        not isinstance(raw, dict) or dependencies["raw"] != content_hash(raw)
    ):
        raise ValueError("proof-plan raw source review binding is stale")
    return raw or {}


def _require_plan_sources(lock, dependencies, materialization):
    if (materialization or {}).get("kind") == "proof-plan":
        if dependencies.get("raw") != native_proof_dependencies(materialization)["raw"]:
            raise ValueError("proof-plan raw source review binding is stale")
        expected = {
            key: digest
            for key, digest in materialization["canonicalInputLock"].items()
            if key.startswith("source:")
        }
    else:
        raw = _review_raw_fingerprints(dependencies, materialization)
        expected = {f"source:{key}": value for key, value in raw.items()}
    _merge_review_source_bindings(lock, dependencies, expected)
    for key, digest in expected.items():
        if key in lock and lock[key] != digest:
            raise ValueError(f"proof-plan source binding is stale: {key}")


def _require_plan_current_inputs(workspace, plan, review, materialization):
    dependencies = review["candidate"]["dependencies"]
    lock = plan["canonicalInputLock"]
    current = workspace.active_dependency_snapshot()
    if not {"cmap", "sync-map"}.issubset(current):
        raise ValueError("proof-plan canonical heads are missing")
    for name, digest in current.items():
        workspace.require_active(name)
        if (
            _locked_canonical_hash(lock, name) != digest
            or dependencies.get(name) != digest
        ):
            raise ValueError(f"proof-plan canonical dependency is stale: {name}")
    if materialization is not None:
        require_current_candidate_dependencies(workspace, materialization, dependencies)
        if materialization.get("kind") == "proof-plan":
            _require_native_plan_binding(materialization, plan)
        if (
            materialization.get("proofPlanHash", plan["proofPlanHash"])
            != plan["proofPlanHash"]
        ):
            raise ValueError("proof-plan assembly binding is stale")
    _require_plan_sources(lock, dependencies, materialization)


def _require_regression_plan(workspace, snapshot, result, review, materialization=None):
    from .proof_plan import ProofPlanCompiler

    plan = ProofPlanCompiler(workspace).load(snapshot["proofPlan"]["artifactId"])
    exact_plan = (
        plan["proofPlanHash"] == snapshot["proofPlan"]["sha256"],
        plan["iterationId"] == snapshot["iterationId"],
        plan["proofPlanHash"] == review["candidate"]["dependencies"].get("proof-plan"),
    )
    if not all(exact_plan):
        raise ValueError("regression proof plan differs from active snapshot")
    _require_plan_current_inputs(workspace, plan, review, materialization)
    contract = plan["regressionContract"]
    if result["contractHash"] != contract["contractHash"]:
        raise ValueError("regression result belongs to another proof-plan contract")
    expected = {item["decisionId"] for item in contract["obligations"]}
    observed = [item["obligationId"] for item in result["results"]]
    if set(observed) != expected or len(observed) != len(expected):
        raise ValueError(
            "regression result does not cover every exact contract obligation"
        )
    for item in result["results"]:
        if item["status"] not in {"preserved", "improved"} or not item["evidenceRefs"]:
            raise ValueError("regression obligation lacks complete positive evidence")


def require_candidate_regression(
    workspace, snapshot, review, regression_path=None, *, materialization=None
):
    """Revalidate the concrete result against the frozen plan without hashing media."""
    result = _candidate_regression(review, regression_path)
    _require_regression_plan(workspace, snapshot, result, review, materialization)
    return result


def _require_regression_artifacts(artifacts):
    for artifact in artifacts:
        if file_fingerprint(Path(artifact["path"]))["sha256"] != artifact["sha256"]:
            raise ValueError("candidate regression artifact changed")


def _source_approval_reference(
    reference: dict[str, Any] | None,
    candidate_sha256: str,
) -> dict[str, Any] | None:
    if reference is None:
        return None
    path = Path(str(reference.get("path") or ""))
    actual = file_fingerprint(path)
    if (
        actual["sha256"] != reference.get("sha256")
        or reference.get("sizeBytes", actual["sizeBytes"]) != actual["sizeBytes"]
    ):
        raise ValueError("source approval fingerprint is stale")
    payload = ApprovalService._load(path)
    exact = (
        payload.get("candidateSha256") == candidate_sha256,
        (payload.get("decision") or payload.get("type")) == "approved",
        (payload.get("actor") or {}).get("type") == "user",
    )
    if not all(exact):
        raise ValueError("source approval does not record exact user acceptance")
    result = {"path": str(path.resolve()), **actual}
    for key in ("scope", "occurredAt", "decidedAt"):
        if key in payload:
            result[key] = payload[key]
    return result


def _require_candidate_approval_snapshot(
    snapshot, fingerprint, materialization, review, regression, finalize
):
    if snapshot is None or snapshot["state"] not in {
        "reviewing",
        "needs-human",
        "approved",
    }:
        raise ValueError("candidate approval requires an active reviewed snapshot")
    candidate = snapshot["candidate"]
    exact = (
        candidate["sha256"] == fingerprint["sha256"],
        candidate["sizeBytes"] == fingerprint["sizeBytes"],
        snapshot["materialization"]["sha256"] == materialization["materializationHash"],
        snapshot["proofPlan"]["sha256"]
        == review["candidate"]["dependencies"].get("proof-plan"),
        snapshot["transcript"] is not None,
    )
    if not all(exact):
        raise ValueError("candidate approval snapshot identity is stale")
    _require_candidate_transcript(snapshot["transcript"], fingerprint["sha256"])
    if finalize:
        bindings = {
            "review": content_hash(review),
            "regressionResult": content_hash(regression),
        }
        for key, digest in bindings.items():
            if snapshot[key] is not None and snapshot[key]["sha256"] != digest:
                raise ValueError(
                    f"candidate approval cannot replace snapshot {key} binding"
                )


def _require_candidate_transcript(transcript, candidate_sha256):
    from avo.transcribe import validate_transcript_payload

    transcript_path = Path(str(transcript.get("locator") or ""))
    actual = file_fingerprint(transcript_path)
    if any(actual[key] != transcript[key] for key in ("sha256", "sizeBytes")):
        raise ValueError("candidate approval transcript artifact changed")
    payload = ApprovalService._load(transcript_path)
    validate_transcript_payload(payload)
    if payload["source"]["sha256"] != candidate_sha256:
        raise ValueError("candidate approval transcript belongs to another candidate")


def _decision_materialization_lock(workspace, materialization, revision, dependencies):
    lock = materialization.get("canonicalInputLock") or {}
    if materialization.get("kind") == "proof-plan":
        expected = require_native_cut_materialization(
            workspace, materialization, Path(materialization["output"]["locator"])
        )
        if any(dependencies.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "review native cut dependencies differ from materialization"
            )
        return {"cmapRevisionHash": lock["cmap"], "syncRevisionHash": lock["sync-map"]}
    if materialization.get("cmapRevisionId") != revision["revisionId"]:
        raise ValueError("materialization is bound to another CMap revision")
    return lock


def _human_artifact(workspace, path):
    path = Path(path)
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(workspace.raw_dir.resolve()):
        raise ValueError("human-final evidence must remain inside the project")
    if not resolved.is_file() or resolved.stat().st_nlink != 1:
        raise ValueError("human-final evidence must be a regular unlinked file")
    return {"path": str(resolved), **file_fingerprint(resolved)}


def _human_document(workspace, path):
    reference = _human_artifact(workspace, path)
    return ApprovalService._load(Path(reference["path"])), reference


def _require_human_artifact(workspace, reference):
    actual = _human_artifact(workspace, reference["path"])
    if (
        reference.get("sha256") != actual["sha256"]
        or reference.get("sizeBytes", actual["sizeBytes"]) != actual["sizeBytes"]
    ):
        raise ValueError("human-final evidence artifact changed")
    return Path(actual["path"])


def _human_reference(workspace, reference):
    return ApprovalService._load(_require_human_artifact(workspace, reference))


def _require_human_decision(decision, fingerprint, dependencies, actor):
    exact = (
        decision.get("authority") == "human-final",
        decision.get("decision") == "approved",
        decision.get("actor") == {"type": "user", "id": actor},
        decision.get("candidateSha256") == fingerprint["sha256"],
        decision.get("dependencyLockSha256") == dependency_lock_hash(dependencies),
        decision.get("automatedReviewDisposition")
        == "superseded-by-explicit-human-approval",
        bool(str(decision.get("instruction") or "").strip()),
    )
    if not all(exact):
        raise ValueError("human-final requires an explicit exact user decision")


def _human_lineage_hash(graph):
    fields = {"pictureLineageHash", "lineageHash", "audiovisualLineageHash"}
    declared = {graph[key] for key in fields if key in graph}
    actual = content_hash(
        {key: value for key, value in graph.items() if key not in fields}
    )
    if declared != {actual}:
        raise ValueError("human-final lineage hash differs from its graph")
    return actual


def _require_human_lineage(materialization, candidate, fingerprint):
    from .lineage import validate_audiovisual_lineage

    graphs = [
        (
            materialization.get("pictureLineage") or {},
            materialization.get("pictureLineageHash"),
        )
    ]
    if "audiovisualLineage" in materialization:
        graphs.append(
            (
                materialization["audiovisualLineage"],
                materialization.get("audiovisualLineageHash"),
            )
        )
    for graph, expected_hash in graphs:
        graph = validate_audiovisual_lineage(graph)
        exact = (
            _human_lineage_hash(graph) == expected_hash,
            graph.get("canonicalInputLock") == materialization["canonicalInputLock"],
            graph.get("projectionHash") == materialization.get("projectionHash"),
        )
        if not all(exact):
            raise ValueError("human-final canonical picture lineage differs")
        for node in graph["nodes"]:
            if node["nodeId"] in graph["rootIds"] and (
                node.get("sha256") != fingerprint["sha256"]
                or Path(node.get("locator", "")).resolve() != candidate.resolve()
            ):
                raise ValueError("human-final lineage output differs from candidate")


def _human_assembly_hash(materialization):
    actual = content_hash(
        {
            key: value
            for key, value in materialization.items()
            if key != "materializationHash"
        }
    )
    if (
        materialization.get("kind") != "assembly"
        or materialization.get("materializationHash") != actual
    ):
        raise ValueError("human-final requires exact assembly materialization")
    return actual


def _require_human_materialization(
    workspace, materialization, candidate, fingerprint, dependencies
):
    if not {"cmap", "sync-map", "bmap", "tracks", "animation"}.issubset(
        workspace.active_dependency_snapshot()
    ):
        raise ValueError("human-final requires every current canonical head")
    output = materialization.get("output") or {}
    expected = {
        "materialization": _human_assembly_hash(materialization),
        "assembly-output": fingerprint["sha256"],
        "picture-lineage": materialization.get("pictureLineageHash"),
        "delivery-fidelity-policy": materialization.get("deliveryFidelityPolicyHash"),
    }
    if any(output.get(key) != fingerprint[key] for key in ("sha256", "sizeBytes")):
        raise ValueError("human-final candidate bytes differ from materialization")
    if Path(output.get("locator", "")).resolve() != candidate.resolve():
        raise ValueError("human-final candidate locator differs from materialization")
    if any(dependencies.get(key) != value for key, value in expected.items()):
        raise ValueError("human-final assembly dependencies differ")
    require_current_candidate_dependencies(workspace, materialization, dependencies)
    _require_human_lineage(materialization, candidate, fingerprint)


def _require_human_report_artifacts(workspace, report, dependencies, candidate_sha):
    for item in report.get("evidence") or []:
        if item.get("candidateSha256", candidate_sha) != candidate_sha:
            raise ValueError(
                "human-final automated evidence belongs to another candidate"
            )
        if item.get("dependencyHashes", dependencies) != dependencies:
            raise ValueError("human-final automated evidence dependencies differ")
        for artifact in item.get("artifacts") or []:
            _require_human_artifact(workspace, artifact)


def _require_human_reports(workspace, reports, dependencies, candidate_sha):
    if set(reports) != {"qc", "transcript-analysis", "watch"}:
        raise ValueError(
            "human-final requires archived QC, transcript and Watch outcomes"
        )
    for reference in reports.values():
        report = _human_reference(workspace, reference)
        hashes = {
            report.get("candidateSha256"),
            report.get("sourceSha256"),
            (report.get("candidate") or {}).get("sha256"),
        } - {None}
        if hashes != {candidate_sha} or report.get("status") != reference.get("status"):
            raise ValueError("human-final automated report identity or outcome differs")
        if not isinstance(reference.get("status"), str) or not reference["status"]:
            raise ValueError("human-final automated outcome is missing")
        _require_human_report_artifacts(workspace, report, dependencies, candidate_sha)


def _require_human_final_bindings(
    workspace, disposition, candidate, fingerprint, materialization, dependencies
):
    from .proof_plan import ProofPlanCompiler

    _require_human_materialization(
        workspace, materialization, candidate, fingerprint, dependencies
    )
    bound = _human_reference(workspace, disposition["materialization"])
    if bound != materialization:
        raise ValueError("human-final assembly artifact differs")
    _human_reference(workspace, disposition["proofPlan"])
    plan = ProofPlanCompiler(workspace).load(Path(disposition["proofPlan"]["path"]))
    if plan["proofPlanHash"] != dependencies.get("proof-plan"):
        raise ValueError("human-final proof plan differs")
    _require_plan_current_inputs(
        workspace, plan, {"candidate": {"dependencies": dependencies}}, materialization
    )
    decision = _human_reference(workspace, disposition["decisionRef"])
    _require_human_decision(
        decision, fingerprint, dependencies, disposition["actor"]["id"]
    )
    source = _source_approval_reference(
        disposition["sourceApprovalRef"], fingerprint["sha256"]
    )
    if source != disposition["sourceApprovalRef"]:
        raise ValueError("human-final original creator acceptance changed")
    _require_human_reports(
        workspace, disposition["automatedEvidence"], dependencies, fingerprint["sha256"]
    )


def require_human_final_disposition(
    workspace, path, *, candidate, fingerprint, materialization, dependencies
):
    """Verify human authority and exact provenance without reclassifying automation."""
    disposition, _ = _human_document(workspace, path)
    body = {
        key: value for key, value in disposition.items() if key != "dispositionHash"
    }
    identity = content_hash(
        {
            "candidate": fingerprint["sha256"],
            "byteSize": fingerprint["sizeBytes"],
            "dependencies": dict(sorted(dependencies.items())),
            "renderProfile": "master",
        }
    )
    exact = (
        disposition.get("dispositionHash") == content_hash(body),
        disposition.get("authority") == "human-final",
        disposition.get("decision") == "approved",
        (disposition.get("actor") or {}).get("type") == "user",
        disposition.get("candidateSha256") == fingerprint["sha256"],
        disposition.get("candidateByteSize") == fingerprint["sizeBytes"],
        disposition.get("candidateIdentityHash") == identity,
        disposition.get("dependencies") == dependencies,
        disposition.get("dependencyLockSha256") == dependency_lock_hash(dependencies),
        disposition.get("automatedOutcomesReclassified") is False,
        disposition.get("regressionPassAsserted") is False,
    )
    if not all(exact):
        raise ValueError("human-final disposition identity or authority differs")
    seed = {
        key: value
        for key, value in disposition.items()
        if key not in {"approvalId", "registeredAt", "dispositionHash"}
    }
    if disposition.get("approvalId") != f"human-final-{content_hash(seed)[:12]}":
        raise ValueError("human-final immutable identity differs from its inputs")
    expected = (
        workspace.timeline_dir / "approvals" / f"{disposition['approvalId']}.json"
    )
    if Path(path).resolve() != expected.resolve():
        raise ValueError("human-final disposition must use its immutable native path")
    _require_human_final_bindings(
        workspace,
        disposition,
        Path(candidate),
        fingerprint,
        materialization,
        dependencies,
    )
    return disposition


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

    def decide_human_final(
        self,
        *,
        candidate,
        dependencies,
        materialization_path,
        proof_plan_path,
        decision_ref,
        source_approval_ref,
        automated_evidence_paths,
        actor,
        reason,
    ):
        """Register explicit final human acceptance; failed automation stays failed."""
        if not actor.strip() or not reason.strip():
            raise ValueError("human-final decision requires a user actor and reason")
        candidate = Path(candidate).resolve()
        if not candidate.is_relative_to(self.workspace.raw_dir.resolve()):
            raise ValueError("human-final candidate must remain inside the project")
        materialization, materialization_ref = _human_document(
            self.workspace, materialization_path
        )
        # Declared identity is used only for cheap metadata preflight, never as
        # proof of candidate bytes. The actual stream hash is required below.
        fingerprint = materialization.get("output") or {}
        _, plan_ref = _human_document(self.workspace, proof_plan_path)
        _human_reference(self.workspace, decision_ref)
        source = _source_approval_reference(source_approval_ref, fingerprint["sha256"])
        if source is None:
            raise ValueError("human-final requires original exact creator acceptance")
        reports = {}
        for name, path in automated_evidence_paths.items():
            report, reference = _human_document(self.workspace, path)
            reports[name] = {**reference, "status": report.get("status")}
        body = {
            "schemaVersion": "1.0.0",
            "authority": "human-final",
            "decision": "approved",
            "actor": {"type": "user", "id": actor},
            "reason": reason,
            "candidateSha256": fingerprint["sha256"],
            "candidateByteSize": fingerprint["sizeBytes"],
            "candidateIdentityHash": content_hash(
                {
                    "candidate": fingerprint["sha256"],
                    "byteSize": fingerprint["sizeBytes"],
                    "dependencies": dict(sorted(dependencies.items())),
                    "renderProfile": "master",
                }
            ),
            "dependencies": dict(dependencies),
            "dependencyLockSha256": dependency_lock_hash(dependencies),
            "materialization": materialization_ref,
            "proofPlan": plan_ref,
            "decisionRef": dict(decision_ref),
            "sourceApprovalRef": source,
            "automatedEvidence": reports,
            "automatedOutcomesReclassified": False,
            "regressionPassAsserted": False,
        }
        _require_human_final_bindings(
            self.workspace, body, candidate, fingerprint, materialization, dependencies
        )
        actual = file_fingerprint(candidate)
        if any(actual[key] != fingerprint.get(key) for key in ("sha256", "sizeBytes")):
            raise ValueError(
                "human-final candidate bytes differ from declared identity"
            )
        # Recheck metadata after the potentially long media read so changed
        # heads or evidence cannot be persisted under the earlier preflight.
        _require_human_final_bindings(
            self.workspace, body, candidate, actual, materialization, dependencies
        )
        body["approvalId"] = f"human-final-{content_hash(body)[:12]}"
        path = self.workspace.timeline_dir / "approvals" / f"{body['approvalId']}.json"
        if path.exists():
            return {
                **require_human_final_disposition(
                    self.workspace,
                    path,
                    candidate=candidate,
                    fingerprint=fingerprint,
                    materialization=materialization,
                    dependencies=dependencies,
                ),
                "path": str(path),
            }
        body["registeredAt"] = now_iso()
        body["dispositionHash"] = content_hash(body)
        write_immutable_json(path, body)
        self.workspace.notify_editlog()
        return {**body, "path": str(path)}

    def decide_candidate(
        self,
        *,
        checkpoint: str,
        review_path: Path,
        materialization_path: Path,
        actor: str,
        reason: str,
        source_approval_ref: dict[str, Any] | None = None,
        regression_path: Path | None = None,
        finalize_snapshot: bool = True,
    ) -> dict[str, Any]:
        """Bind an existing user decision to real current non-cut checkpoint evidence."""
        from .pipeline import TimelinePipeline

        if checkpoint not in {"motion-proof", "pre-master", "deliver"}:
            raise ValueError("candidate decision requires a non-cut checkpoint")
        if not actor.strip() or not reason.strip():
            raise ValueError("candidate decision requires a user actor and reason")
        review = self._load(review_path)
        validate_document(review, "avo.review-evidence.schema.json")
        materialization = self._load(materialization_path)
        candidate, fingerprint = _candidate_materialization(
            self.workspace, review, materialization
        )
        require_candidate_review(
            review,
            checkpoint=checkpoint,
            candidate=candidate,
            fingerprint=fingerprint,
            dependencies=review["candidate"]["dependencies"],
        )
        regression = _candidate_regression(review, regression_path)
        source_reference = _source_approval_reference(
            source_approval_ref, fingerprint["sha256"]
        )
        pipeline = TimelinePipeline(self.workspace)
        snapshot = pipeline.active_candidate_snapshot()
        _require_candidate_approval_snapshot(
            snapshot,
            fingerprint,
            materialization,
            review,
            regression,
            finalize_snapshot,
        )
        _require_regression_plan(
            self.workspace, snapshot, regression, review, materialization
        )
        if finalize_snapshot and snapshot["state"] == "approved":
            return self._existing_candidate_approval(
                snapshot, review, actor, reason, source_reference
            )
        registered_at = now_iso()
        approval = {
            "schemaVersion": "1.0.0",
            "checkpoint": checkpoint,
            "decision": "approved",
            "candidateIdentityHash": review["candidate"]["identityHash"],
            "candidateSha256": fingerprint["sha256"],
            "dependencyLockSha256": review["dependencyLockSha256"],
            "actor": {"type": "user", "id": actor},
            "reason": reason,
            "decidedAt": registered_at,
            "registeredAt": registered_at,
            "review": {
                "path": str(Path(review_path).resolve()),
                **file_fingerprint(Path(review_path)),
                "contentHash": content_hash(review),
            },
            "materialization": {
                "path": str(Path(materialization_path).resolve()),
                **file_fingerprint(Path(materialization_path)),
                "materializationHash": materialization["materializationHash"],
            },
            "regressionResult": {
                "sha256": content_hash(regression),
                "candidateSha256": fingerprint["sha256"],
            },
        }
        if source_reference is not None:
            approval["sourceApprovalRef"] = source_reference
            approval["decisionBasis"] = (
                "prior-exact-master-acceptance-and-current-native-authorization"
            )
        if regression_path is not None:
            approval["regressionResult"].update(
                path=str(Path(regression_path).resolve()),
                fileSha256=file_fingerprint(Path(regression_path))["sha256"],
            )
        approval["approvalId"] = f"candidate-approval-{content_hash(approval)[:12]}"
        path = (
            self.workspace.timeline_dir / "approvals" / f"{approval['approvalId']}.json"
        )
        write_immutable_json(path, approval)
        if finalize_snapshot:
            self._approve_candidate_snapshot(
                pipeline, snapshot, approval, review, regression
            )
        self.workspace.notify_editlog()
        return {**approval, "path": str(path)}

    def _existing_candidate_approval(
        self,
        snapshot: dict[str, Any],
        review: dict[str, Any],
        actor: str,
        reason: str,
        source_reference: dict[str, Any] | None,
    ) -> dict[str, Any]:
        reference = snapshot["approval"]
        path = (
            self.workspace.timeline_dir
            / "approvals"
            / f"{reference['artifactId']}.json"
        )
        approval = self._load(path)
        exact = (
            content_hash(approval) == reference["sha256"],
            approval["checkpoint"] == review["checkpoint"],
            approval["candidateIdentityHash"] == review["candidate"]["identityHash"],
            approval["dependencyLockSha256"] == review["dependencyLockSha256"],
            approval["review"]["contentHash"] == content_hash(review),
            approval["actor"] == {"type": "user", "id": actor},
            approval["reason"] == reason,
            approval.get("sourceApprovalRef") == source_reference,
        )
        if not all(exact):
            raise ValueError(
                "approved snapshot cannot replace its exact candidate decision"
            )
        return {**approval, "path": str(path)}

    @staticmethod
    def _approve_candidate_snapshot(pipeline, snapshot, approval, review, regression):
        candidate_hash = review["candidate"]["sha256"]
        pipeline.record_candidate_snapshot(
            state="approved",
            candidate=snapshot["candidate"],
            iteration_id=snapshot["iterationId"],
            proof_plan={
                **snapshot["proofPlan"],
                "iterationId": snapshot["iterationId"],
            },
            materialization={
                **snapshot["materialization"],
                "candidateSha256": candidate_hash,
            },
            transcript={
                "fingerprint": snapshot["transcript"],
                "sourceSha256": candidate_hash,
            },
            review={
                **(
                    snapshot["review"]
                    or {
                        "artifactId": f"{review['checkpoint']}-review",
                        "sha256": content_hash(review),
                    }
                ),
                "candidateSha256": candidate_hash,
                "proofPlanSha256": snapshot["proofPlan"]["sha256"],
            },
            regression_result={
                **(
                    snapshot["regressionResult"]
                    or {
                        "artifactId": "regression-result",
                        "sha256": content_hash(regression),
                    }
                ),
                "candidateSha256": candidate_hash,
            },
            approval={
                "artifactId": approval["approvalId"],
                "sha256": content_hash(approval),
                "candidateSha256": candidate_hash,
            },
            expected_active_snapshot_hash=snapshot["snapshotHash"],
        )

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
        if decision == "approved":
            _require_complete_automated_review(review)
        lock = _decision_materialization_lock(
            self.workspace,
            materialization,
            revision,
            review["candidate"]["dependencies"],
        )
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
