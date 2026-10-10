"""Append-only proof iteration history and regression-contract compilation."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .store import ArtifactStore, now_iso

_NUMBERED_ID = re.compile(r"^(?P<prefix>[a-z][a-z0-9-]*?)-(?P<number>[0-9]{4,})$")
_DECISION_STATES = {
    "active",
    "resolved",
    "superseded",
    "rejected",
    "awaiting-human",
    "not-applicable",
}
_CONTRACT_STATES = {"active", "rejected", "awaiting-human"}
_REWORK_ORIGINS = {
    "user-scope-change",
    "creator-preference-refinement",
    "agent-reasoning-defect",
    "implementation-defect",
    "avo-capability-gap",
    "source-limitation",
    "external-dependency-failure",
    "unknown",
}


class IterationLedgerError(RuntimeError):
    """Raised when iteration history would become ambiguous or inconsistent."""


def _attach_cutting_refs(request):
    cutting_refs = request.pop("cuttingRefs", None)
    if cutting_refs is None:
        return
    if not isinstance(cutting_refs, dict):
        raise IterationLedgerError("cutting references must be an object")
    for role, reference in cutting_refs.items():
        try:
            validate_document(reference, "avo.cutting.schema.json#/$defs/artifactRef")
        except ContractError as exc:
            raise IterationLedgerError(f"invalid cutting reference: {exc}") from exc
        request.setdefault("findings", []).append(
            {
                "evidenceId": f"cutting-{role}",
                "sha256": reference["sha256"],
                "kind": f"cutting-{role}",
            }
        )
    request.setdefault("intent", {})["cutting"] = cutting_refs


def _actor(value: str | dict[str, Any]) -> dict[str, str]:
    if isinstance(value, dict):
        actor = {
            key: str(item).strip() for key, item in value.items() if str(item).strip()
        }
    else:
        actor = {"type": "agent", "id": str(value).strip()}
    if not actor.get("id"):
        raise IterationLedgerError("actor identity is required")
    actor.setdefault("type", "agent")
    return actor


def _next_id(prefix: str, values: set[str]) -> str:
    largest = 0
    for value in values:
        match = _NUMBERED_ID.fullmatch(value)
        if match and match.group("prefix") == prefix:
            largest = max(largest, int(match.group("number")))
    return f"{prefix}-{largest + 1:04d}"


def _seal(document: dict[str, Any], hash_field: str) -> dict[str, Any]:
    result = deepcopy(document)
    result[hash_field] = document_hash_excluding(result, hash_field)
    return result


class IterationLedgerService:
    """Store complete iteration memory without retaining proof media bytes."""

    def __init__(self, workspace: Any, *, clock=now_iso):
        self.workspace = workspace
        self.clock = clock
        self.path = Path(workspace.timeline_dir) / "iteration-ledger.json"
        self.store = ArtifactStore(self.path, clock=clock)
        if not self.path.exists():
            provider = str((workspace.project or {}).get("provider") or "").strip()
            if not provider:
                raise IterationLedgerError("provider identity is required")
            self.store.initialize(
                artifact_type="iteration-ledger",
                artifact_id=f"{workspace.video_id}:iteration-ledger",
                video_id=str(workspace.video_id),
                provider=provider,
                timeline_domain="cmap-output",
            )

    def _empty(self) -> dict[str, Any]:
        video_id = str(self.workspace.video_id)
        provider = str((self.workspace.project or {}).get("provider") or "")
        body = {
            "schemaVersion": "1.0.0",
            "ledgerId": f"ledger-{content_hash(video_id)[:12]}",
            "videoId": video_id,
            "provider": provider,
            "currentIterationId": None,
            "iterations": [],
            "decisions": [],
            "reworkItems": [],
            "artifactFingerprints": [],
            "ledgerHash": "",
        }
        return _seal(body, "ledgerHash")

    @staticmethod
    def _validate(ledger: dict[str, Any]) -> dict[str, Any]:
        expected = ledger.get("ledgerHash")
        actual = document_hash_excluding(ledger, "ledgerHash")
        if expected != actual:
            raise IterationLedgerError("iteration ledger hash mismatch")
        try:
            validate_document(ledger, "avo.iteration-ledger.schema.json")
        except ContractError as exc:
            raise IterationLedgerError(f"invalid iteration ledger: {exc}") from exc
        return ledger

    def current(self) -> dict[str, Any]:
        index = self.store.load_index()
        if index["headRevisionId"] is None:
            return self._empty()
        revision = self.store.revision(index["headRevisionId"])
        return deepcopy(self._validate(revision["snapshot"]))

    @staticmethod
    def fingerprint_candidate(path: Path) -> dict[str, Any]:
        return file_fingerprint(Path(path))

    def _decision(
        self,
        request: dict[str, Any],
        *,
        decision_id: str,
        iteration_id: str,
        timestamp: str,
    ) -> tuple[dict[str, Any], list[str]]:
        value = deepcopy(request)
        supersedes = [str(item) for item in value.pop("supersedes", [])]
        value.update(
            {
                "decisionId": decision_id,
                "originIterationId": iteration_id,
                "status": str(value.get("status") or "active"),
                "supersededBy": None,
                "evidenceRefs": list(value.get("evidenceRefs") or []),
                "riskWindows": list(value.get("riskWindows") or []),
                "updatedAt": timestamp,
            }
        )
        if value["status"] not in _DECISION_STATES:
            raise IterationLedgerError(f"invalid decision status: {value['status']}")
        return value, supersedes

    def _rework(
        self,
        request: dict[str, Any],
        *,
        rework_id: str,
        iteration_id: str,
        actor: dict[str, str],
    ) -> dict[str, Any]:
        value = deepcopy(request)
        origin = str(value.get("origin") or "unknown")
        if origin not in _REWORK_ORIGINS:
            raise IterationLedgerError(f"invalid rework origin: {origin}")
        evidence_refs = list(value.get("evidenceRefs") or [])
        if origin != "unknown" and not evidence_refs:
            raise IterationLedgerError(
                "non-unknown rework classification requires evidence"
            )
        capability_gap = value.get("capabilityGap")
        if origin == "avo-capability-gap" and not isinstance(capability_gap, dict):
            raise IterationLedgerError(
                "AVO capability-gap classification requires capability details"
            )
        confidence = float(value.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise IterationLedgerError("rework confidence must be between 0 and 1")
        value.update(
            {
                "reworkId": rework_id,
                "iterationId": iteration_id,
                "reworkGroupId": str(value.get("reworkGroupId") or rework_id),
                "origin": origin,
                "impact": deepcopy(
                    value.get("impact")
                    or {"affectedArtifacts": [], "programWindows": []}
                ),
                "evidenceRefs": evidence_refs,
                "confidence": confidence,
                "capabilityGap": capability_gap,
                "supersedes": value.get("supersedes"),
                "classifiedBy": deepcopy(value.get("classifiedBy") or actor),
            }
        )
        return value

    def _commit(
        self,
        ledger: dict[str, Any],
        *,
        actor: str | dict[str, Any],
        reason: str,
        expected_head_hash: str | None,
        stable_id: str,
        collection: str,
        operation: str = "add",
    ) -> dict[str, Any]:
        ledger = _seal(ledger, "ledgerHash")
        self._validate(ledger)
        revision = self.store.append_revision(
            snapshot=ledger,
            actor=actor,
            reason=reason,
            expected_head_hash=expected_head_hash,
            diff=[
                {
                    "opId": "diff-0001",
                    "op": operation,
                    "target": {"collection": collection, "stableId": stable_id},
                    "after": {"ledgerHash": ledger["ledgerHash"]},
                    "reason": reason,
                    "actorIntent": "preserve complete iteration history",
                    "affectedTimeRanges": [],
                }
            ],
        )
        return {"ledger": ledger, "revision": revision}

    def record_iteration(
        self,
        request: dict[str, Any],
        *,
        actor: str | dict[str, Any],
        reason: str,
        expected_head_hash: str | None = None,
    ) -> dict[str, Any]:
        ledger = self.current()
        actual_head = self.store.head_hash()
        expected = actual_head if expected_head_hash is None else expected_head_hash
        request = deepcopy(request)
        _attach_cutting_refs(request)
        sequence = len(ledger["iterations"]) + 1
        iteration_ids = {item["iterationId"] for item in ledger["iterations"]}
        iteration_id = str(
            request.get("iterationId") or _next_id("iteration", iteration_ids)
        )
        if iteration_id in iteration_ids:
            raise IterationLedgerError(f"iteration already exists: {iteration_id}")
        parent_id = request.get("parentIterationId", ledger["currentIterationId"])
        if parent_id is not None and parent_id not in iteration_ids:
            raise IterationLedgerError(f"parent iteration does not exist: {parent_id}")
        timestamp = str(request.get("createdAt") or self.clock())
        actor_value = _actor(actor)

        decision_ids = {item["decisionId"] for item in ledger["decisions"]}
        created_decisions: list[dict[str, Any]] = []
        supersessions: list[tuple[str, str]] = []
        for item in request.get("decisions") or []:
            decision_id = str(
                item.get("decisionId") or _next_id("decision", decision_ids)
            )
            if decision_id in decision_ids:
                raise IterationLedgerError(f"decision already exists: {decision_id}")
            decision_ids.add(decision_id)
            decision, supersedes = self._decision(
                item,
                decision_id=decision_id,
                iteration_id=iteration_id,
                timestamp=timestamp,
            )
            created_decisions.append(decision)
            supersessions.extend((old_id, decision_id) for old_id in supersedes)

        decisions_by_id = {item["decisionId"]: item for item in ledger["decisions"]}
        for old_id, replacement_id in supersessions:
            if old_id not in decisions_by_id:
                raise IterationLedgerError(
                    f"superseded decision does not exist: {old_id}"
                )
            old = decisions_by_id[old_id]
            if old["status"] == "superseded":
                raise IterationLedgerError(f"decision is already superseded: {old_id}")
            old["status"] = "superseded"
            old["supersededBy"] = replacement_id
            old["updatedAt"] = timestamp
        ledger["decisions"].extend(created_decisions)

        rework_ids = {item["reworkId"] for item in ledger["reworkItems"]}
        superseded_rework = {
            str(item["supersedes"])
            for item in ledger["reworkItems"]
            if item.get("supersedes")
        }
        created_rework: list[dict[str, Any]] = []
        for item in request.get("reworkItems") or []:
            rework_id = str(item.get("reworkId") or _next_id("rework", rework_ids))
            if rework_id in rework_ids:
                raise IterationLedgerError(f"rework item already exists: {rework_id}")
            rework_ids.add(rework_id)
            classification = self._rework(
                item,
                rework_id=rework_id,
                iteration_id=iteration_id,
                actor=actor_value,
            )
            supersedes = classification.get("supersedes")
            if supersedes:
                if supersedes not in rework_ids:
                    raise IterationLedgerError(
                        f"superseded rework item does not exist: {supersedes}"
                    )
                if supersedes in superseded_rework:
                    raise IterationLedgerError(
                        f"rework item is already superseded: {supersedes}"
                    )
                superseded_rework.add(str(supersedes))
            created_rework.append(classification)
        ledger["reworkItems"].extend(created_rework)

        candidate = deepcopy(request.get("candidate"))
        iteration = {
            "iterationId": iteration_id,
            "sequence": sequence,
            "parentIterationId": parent_id,
            "intent": deepcopy(request.get("intent") or {}),
            "canonicalBasis": deepcopy(request.get("canonicalBasis") or {}),
            "proofPlanRef": deepcopy(request.get("proofPlanRef") or {}),
            "candidate": candidate,
            "findings": deepcopy(request.get("findings") or []),
            "feedback": deepcopy(request.get("feedback") or []),
            "decisionIds": [item["decisionId"] for item in created_decisions],
            "reworkItemIds": [item["reworkId"] for item in created_rework],
            "state": str(request.get("state") or "planned"),
            "createdAt": timestamp,
        }
        ledger["iterations"].append(iteration)
        ledger["currentIterationId"] = iteration_id
        if candidate is not None:
            ledger["artifactFingerprints"].append(
                {
                    "artifactId": f"candidate-{iteration_id}",
                    "mediaClass": str(request.get("candidateMediaClass") or "proof"),
                    "fingerprint": deepcopy(candidate),
                    "state": "current",
                }
            )
        result = self._commit(
            ledger,
            actor=actor_value,
            reason=reason,
            expected_head_hash=expected,
            stable_id=iteration_id,
            collection="iterations",
        )
        return {**result, "iteration": iteration}

    def migrate_unknown_history(
        self,
        *,
        source_sha256: str,
        note: str,
        actor: str | dict[str, Any],
        expected_head_hash: str | None = None,
    ) -> dict[str, Any]:
        request = {
            "intent": {"migration": "partial-history", "note": note},
            "canonicalBasis": {"legacyHistory": source_sha256},
            "proofPlanRef": {
                "artifactId": "legacy-history",
                "sha256": source_sha256,
                "locator": None,
                "tombstoned": True,
            },
            "feedback": [{"status": "unknown", "note": note}],
            "reworkItems": [
                {
                    "origin": "unknown",
                    "summary": note,
                    "impact": {"affectedArtifacts": [], "programWindows": []},
                    "evidenceRefs": [],
                    "confidence": 0.0,
                    "capabilityGap": None,
                    "supersedes": None,
                }
            ],
            "state": "reviewed",
        }
        return self.record_iteration(
            request,
            actor=actor,
            reason="migrate unknown iteration history",
            expected_head_hash=expected_head_hash,
        )

    def mark_iteration_cleaned(
        self,
        iteration_id: str,
        *,
        actor: str | dict[str, Any],
        reason: str,
        expected_head_hash: str | None = None,
    ) -> dict[str, Any]:
        ledger = self.current()
        actual_head = self.store.head_hash()
        expected = actual_head if expected_head_hash is None else expected_head_hash
        iteration = next(
            (
                item
                for item in ledger["iterations"]
                if item["iterationId"] == iteration_id
            ),
            None,
        )
        if iteration is None:
            raise IterationLedgerError(f"iteration does not exist: {iteration_id}")
        iteration["state"] = "cleaned"
        candidate = iteration.get("candidate")
        if candidate is not None:
            candidate["locator"] = None
            for item in ledger["artifactFingerprints"]:
                if item["fingerprint"]["sha256"] == candidate["sha256"]:
                    item["fingerprint"]["locator"] = None
                    item["state"] = "tombstoned"
        return self._commit(
            ledger,
            actor=actor,
            reason=reason,
            expected_head_hash=expected,
            stable_id=iteration_id,
            collection="iterations",
            operation="replace",
        )

    def set_decision_status(
        self,
        decision_id: str,
        status: str,
        *,
        actor: str | dict[str, Any],
        reason: str,
        superseded_by: str | None = None,
        expected_head_hash: str | None = None,
    ) -> dict[str, Any]:
        if status not in _DECISION_STATES:
            raise IterationLedgerError(f"invalid decision status: {status}")
        ledger = self.current()
        actual_head = self.store.head_hash()
        expected = actual_head if expected_head_hash is None else expected_head_hash
        by_id = {item["decisionId"]: item for item in ledger["decisions"]}
        decision = by_id.get(decision_id)
        if decision is None:
            raise IterationLedgerError(f"decision does not exist: {decision_id}")
        if status == "superseded":
            if not superseded_by:
                raise IterationLedgerError(
                    "superseded status requires a replacement decision"
                )
            if superseded_by == decision_id or superseded_by not in by_id:
                raise IterationLedgerError("replacement decision is invalid")
            cursor = superseded_by
            visited = {decision_id}
            while cursor is not None:
                if cursor in visited:
                    raise IterationLedgerError("decision supersession cycle detected")
                visited.add(cursor)
                cursor = by_id[cursor].get("supersededBy")
        elif superseded_by is not None:
            raise IterationLedgerError(
                "supersededBy is valid only for superseded status"
            )
        decision["status"] = status
        decision["supersededBy"] = superseded_by
        decision["updatedAt"] = self.clock()
        return self._commit(
            ledger,
            actor=actor,
            reason=reason,
            expected_head_hash=expected,
            stable_id=decision_id,
            collection="decisions",
            operation="replace",
        )

    @staticmethod
    def _conflicts(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        live = {
            item["decisionId"]: item
            for item in decisions
            if item["status"] in _CONTRACT_STATES
        }
        pairs: set[tuple[str, str]] = set()
        for decision_id, item in live.items():
            for other in item["scope"].get("conflictsWith") or []:
                other_id = str(other)
                if other_id in live and other_id != decision_id:
                    pairs.add(tuple(sorted((decision_id, other_id))))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in live.values():
            constraint = item["scope"].get("constraintId")
            if constraint is not None and "value" in item["scope"]:
                grouped.setdefault(str(constraint), []).append(item)
        for items in grouped.values():
            for left_index, left in enumerate(items):
                for right in items[left_index + 1 :]:
                    if left["scope"]["value"] != right["scope"]["value"]:
                        pair = (left["decisionId"], right["decisionId"])
                        pairs.add(tuple(sorted(pair)))
        return [
            {
                "decisionIds": list(pair),
                "reason": "explicitly conflicting live decisions",
                "status": "needs-human",
            }
            for pair in sorted(pairs)
        ]

    def compile_regression_contract(
        self, iteration_id: str | None = None
    ) -> dict[str, Any]:
        ledger = self.current()
        iteration_id = iteration_id or ledger["currentIterationId"]
        if iteration_id is None or not any(
            item["iterationId"] == iteration_id for item in ledger["iterations"]
        ):
            raise IterationLedgerError("regression contract requires a known iteration")
        obligations = [
            deepcopy(item)
            for item in ledger["decisions"]
            if item["status"] in _CONTRACT_STATES
        ]
        windows: dict[str, dict[str, Any]] = {}
        for decision in ledger["decisions"]:
            for window in decision["riskWindows"]:
                window_id = window["windowId"]
                existing = windows.get(window_id)
                if existing is not None and existing != window:
                    raise IterationLedgerError(
                        f"historical risk window identity changed: {window_id}"
                    )
                windows[window_id] = deepcopy(window)
        body = {
            "contractId": f"contract-{iteration_id}",
            "ledgerHash": ledger["ledgerHash"],
            "iterationId": iteration_id,
            "obligations": obligations,
            "historicalRiskWindows": list(windows.values()),
            "conflicts": self._conflicts(ledger["decisions"]),
            "contractHash": "",
        }
        contract = _seal(body, "contractHash")
        try:
            validate_document(
                contract,
                "avo.iteration-ledger.schema.json#/$defs/regressionContract",
            )
        except ContractError as exc:
            raise IterationLedgerError(f"invalid regression contract: {exc}") from exc
        return contract
