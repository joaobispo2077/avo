"""Strict contracts and persistence invariants for batch Shorts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from avo.paths import schema_path

SCHEMA_NAMES = {
    "request": "avo.shorts-batch.schema.json",
    "plan": "avo.shorts-plan.schema.json",
    "status": "avo.shorts-status.schema.json",
    "composition": "avo.shorts-composition.schema.json",
}


class ContractValidationError(ValueError):
    """A Shorts contract or cross-document invariant is invalid."""


def load_schema(kind: str) -> dict[str, Any]:
    """Load one public Shorts schema by its stable contract kind."""
    try:
        name = SCHEMA_NAMES[kind]
    except KeyError as exc:
        known = ", ".join(sorted(SCHEMA_NAMES))
        raise ContractValidationError(
            f"unknown Shorts contract kind {kind!r}; expected one of: {known}"
        ) from exc
    path = schema_path(name)
    if not path.is_file():
        raise ContractValidationError(f"missing Shorts {kind} schema: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON text for hashing and persistence."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(value: Any) -> str:
    """Hash canonical content with SHA-256."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def plan_hash(plan: Mapping[str, Any]) -> str:
    """Hash an immutable plan without recursively including planHash."""
    payload = deepcopy(dict(plan))
    payload.pop("planHash", None)
    return content_hash(payload)


def _error_path(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return path or "<root>"


def _schema_validate(document: Mapping[str, Any], kind: str) -> None:
    validator = Draft202012Validator(load_schema(kind))
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        first = errors[0]
        raise ContractValidationError(
            f"{kind} contract invalid at {_error_path(first)}: {first.message}"
        )


def _unique(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ContractValidationError(f"{label} must be unique")


def _validate_request_invariants(request: Mapping[str, Any]) -> None:
    candidates = list(request.get("candidates") or [])
    ids = [candidate.get("id") for candidate in candidates]
    orders = [candidate.get("order") for candidate in candidates]
    _unique(ids, "candidate IDs")
    _unique(orders, "candidate order values")
    requested = request.get("requestedCount")
    if requested != len(candidates):
        raise ContractValidationError(
            "requestedCount must equal the number of candidate records "
            f"({requested!r} != {len(candidates)})"
        )

    insertion_ids = [item.get("id") for item in request.get("insertions") or []]
    _unique(insertion_ids, "insertion IDs")
    correction_omissions = [
        correction
        for correction in request.get("corrections") or []
        if correction.get("operation") == "omit"
    ]
    for correction in correction_omissions:
        if not correction.get("approved") or not correction.get("reason"):
            raise ContractValidationError(
                "caption omission corrections require approval and a reason"
            )


def _validate_plan_invariants(plan: Mapping[str, Any]) -> None:
    items = list(plan.get("items") or [])
    ids = [item.get("id") for item in items]
    orders = [item.get("order") for item in items]
    _unique(ids, "plan item IDs")
    _unique(orders, "plan item order values")
    requested = plan.get("requestedCount")
    resolved = plan.get("resolvedCount")
    if requested != resolved or resolved != len(items):
        raise ContractValidationError(
            "requestedCount, resolvedCount, and plan item count must match"
        )
    expected = plan_hash(plan)
    if plan.get("planHash") != expected:
        raise ContractValidationError(
            f"planHash does not match canonical plan content: expected {expected}"
        )


def _validate_status_invariants(status: Mapping[str, Any]) -> None:
    items = list(status.get("items") or [])
    _unique([item.get("shortId") for item in items], "status short IDs")
    if status.get("deliveryComplete"):
        incomplete = [
            item.get("shortId")
            for item in items
            if item.get("state") != "delivered" or item.get("dirty")
        ]
        if incomplete:
            raise ContractValidationError(
                "deliveryComplete requires every item delivered and clean; "
                f"incomplete: {', '.join(str(item) for item in incomplete)}"
            )


def validate_document(document: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    """Validate one contract and its non-schema cross-field invariants."""
    _schema_validate(document, kind)
    if kind == "request":
        _validate_request_invariants(document)
    elif kind == "plan":
        _validate_plan_invariants(document)
    elif kind == "status":
        _validate_status_invariants(document)
    return document


def load_document(path: Path | str, kind: str) -> dict[str, Any]:
    """Read and validate a JSON contract from disk."""
    resolved = Path(path)
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"cannot read {kind} document {resolved}: {exc}") from exc
    validate_document(document, kind)
    return document


def require_plan_approval(plan: Mapping[str, Any]) -> None:
    """Block expensive work until the immutable plan is explicitly approved."""
    approval = plan.get("planApproval") or {}
    if approval.get("status") != "approved" or not approval.get("reference"):
        raise ContractValidationError(
            "plan approval is required before proof or master build"
        )


def ensure_plan_status_match(
    plan: Mapping[str, Any], status: Mapping[str, Any]
) -> None:
    """Ensure mutable status belongs to the exact immutable plan."""
    if status.get("batchId") != plan.get("batchId"):
        raise ContractValidationError("status batchId does not match plan batchId")
    if status.get("planHash") != plan.get("planHash"):
        raise ContractValidationError("status planHash does not match plan planHash")


def atomic_write_json(path: Path | str, document: Mapping[str, Any]) -> Path:
    """Atomically replace a JSON document in its destination directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination


_ITEM_TRANSITIONS = {
    "pending": {"preparing", "blocked"},
    "preparing": {"composition-ready", "failed"},
    "composition-ready": {"validating", "failed"},
    "validating": {"proof-rendering", "failed"},
    "proof-rendering": {"proof-ready", "failed"},
    "proof-ready": {"proof-approved", "dirty", "failed"},
    "proof-approved": {"dirty", "master-rendering"},
    "dirty": {"preparing", "blocked"},
    "failed": {"preparing", "blocked"},
    "master-rendering": {"master-qc", "failed"},
    "master-qc": {"delivered", "failed"},
    "delivered": {"dirty"},
    "blocked": {"pending", "preparing"},
}


def transition_item(item: Mapping[str, Any], state: str, *, reason: str | None = None) -> dict[str, Any]:
    current = str(item["state"])
    if state not in _ITEM_TRANSITIONS.get(current, set()):
        raise ContractValidationError(f"invalid Shorts item transition: {current} -> {state}")
    updated = dict(item)
    updated["state"] = state
    if state == "dirty":
        updated["dirty"] = True
        updated["dirtyReasons"] = [*(item.get("dirtyReasons") or []), reason or "superseded-input"]
    return updated


def validate_promotion_evidence(
    status: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    """Require common exact candidate/dependency identity for every promoted Short."""
    reviews = {item.get("shortId"): item for item in manifest.get("watchReviews") or []}
    approvals = manifest.get("approvals") or []
    if not approvals:
        raise ContractValidationError("promotion requires exact approvals")
    required_hashes = (
        "candidateHash", "candidateIdentityHash",
        "dependencyLockSha256", "evidenceBundleSha256",
    )
    for item in status.get("items") or []:
        short_id = item.get("shortId")
        proof = next(
            (
                artifact for artifact in reversed(item.get("artifacts") or [])
                if artifact.get("kind") == "proof"
                and artifact.get("revision") == item.get("proofRevision")
            ),
            None,
        )
        review = reviews.get(short_id)
        if proof is None or review is None:
            raise ContractValidationError(
                f"promotion requires current proof and Watch evidence for {short_id}"
            )
        if review.get("candidateHash") != proof.get("hash"):
            raise ContractValidationError(f"Watch candidate hash is stale for {short_id}")
        if review.get("proofRevision") != item.get("proofRevision"):
            raise ContractValidationError(f"Watch proof revision is stale for {short_id}")
        if not review.get("reference"):
            raise ContractValidationError(f"Watch reference is required for {short_id}")
        for field in required_hashes[1:]:
            if len(str(review.get(field) or "")) != 64:
                raise ContractValidationError(
                    f"Watch {field} is missing or invalid for {short_id}"
                )
    for approval in approvals:
        if approval.get("status") == "approved":
            for field in required_hashes:
                if len(str(approval.get(field) or "")) != 64:
                    raise ContractValidationError(
                        f"approved promotion decision requires exact {field}"
                    )
            if int(approval.get("proofRevision") or 0) < 1:
                raise ContractValidationError(
                    "approved promotion decisions require proofRevision"
                )
