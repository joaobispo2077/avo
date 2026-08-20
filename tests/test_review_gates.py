from __future__ import annotations

import pytest

from avo.timeline.review import (
    CHECKPOINT_POLICIES,
    GateError,
    approval_is_current,
    evaluate_gate,
)

CANDIDATE = "a" * 64
IDENTITY = "b" * 64
LOCK = "c" * 64
DEPS = {"cmap": "d" * 64, "sync-map": "e" * 64}


def evidence(
    kind,
    *,
    status="pass",
    mode="full",
    required=0,
    reviewed=0,
    profile="exact-candidate",
):
    return {
        "kind": kind,
        "status": status,
        "candidateHash": CANDIDATE,
        "candidateIdentityHash": IDENTITY,
        "dependencyLockSha256": LOCK,
        "dependencyHashes": DEPS,
        "dependencyProfile": profile,
        "scope": {"mode": mode},
        "coverage": {"requiredWindows": required, "reviewedWindows": reviewed},
    }


@pytest.mark.parametrize("checkpoint", CHECKPOINT_POLICIES)
def test_checkpoint_requires_complete_current_unique_evidence(checkpoint):
    required = CHECKPOINT_POLICIES[checkpoint]["required"]
    items = [evidence(kind) for kind in required]
    if "sync" in required:
        for item in items:
            if item["kind"] == "sync":
                item["dependencyProfile"] = "raw-sync"
    if "rights" in required:
        for item in items:
            if item["kind"] == "rights":
                item["dependencyProfile"] = "source-rights"
                item["dependencyHashes"] = {"sourceUsage": "f" * 64}
    deps = dict(DEPS)
    if "rights" in required:
        deps["sourceUsage"] = "f" * 64
    for item in items:
        if item.get("dependencyProfile") == "exact-candidate":
            item["dependencyHashes"] = deps
    assert (
        evaluate_gate(
            checkpoint,
            CANDIDATE,
            deps,
            items,
            candidate_identity_hash=IDENTITY,
            dependency_lock_sha256=LOCK,
        )
        == "ai-passed"
    )
    with pytest.raises(GateError, match="missing current evidence"):
        evaluate_gate(
            checkpoint,
            CANDIDATE,
            deps,
            items[:-1],
            candidate_identity_hash=IDENTITY,
            dependency_lock_sha256=LOCK,
        )


def test_duplicate_incomplete_window_and_unjustified_na_block():
    required = CHECKPOINT_POLICIES["cut-proof"]["required"]
    items = [evidence(kind) for kind in required]
    next(item for item in items if item["kind"] == "sync")["dependencyProfile"] = (
        "raw-sync"
    )
    items.append(evidence("watch"))
    with pytest.raises(GateError, match="duplicate"):
        evaluate_gate("cut-proof", CANDIDATE, DEPS, items)

    items = [evidence(kind) for kind in required]
    next(item for item in items if item["kind"] == "sync")["dependencyProfile"] = (
        "raw-sync"
    )
    watch = next(item for item in items if item["kind"] == "watch")
    watch["coverage"] = {"requiredWindows": 3, "reviewedWindows": 2}
    with pytest.raises(GateError):
        evaluate_gate("cut-proof", CANDIDATE, DEPS, items)

    items = [evidence(kind) for kind in required]
    sync = next(item for item in items if item["kind"] == "sync")
    sync["dependencyProfile"] = "raw-sync"
    sync["status"] = "not-applicable"
    sync["notApplicable"] = {"rationale": "single clock"}
    with pytest.raises(GateError):
        evaluate_gate("cut-proof", CANDIDATE, DEPS, items)


def test_approval_binding_requires_exact_identity():
    approval = {
        "checkpoint": "pre-master",
        "decision": "approved",
        "candidateIdentityHash": IDENTITY,
        "candidateSha256": CANDIDATE,
        "dependencyLockSha256": LOCK,
    }
    assert approval_is_current(
        approval,
        checkpoint="pre-master",
        candidate_identity_hash=IDENTITY,
        candidate_sha256=CANDIDATE,
        dependency_lock_sha256=LOCK,
    )
    assert not approval_is_current(
        approval,
        checkpoint="pre-master",
        candidate_identity_hash="0" * 64,
        candidate_sha256=CANDIDATE,
        dependency_lock_sha256=LOCK,
    )
