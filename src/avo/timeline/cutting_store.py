"""Immutable cutting evidence and source-stable, crash-consumed repair budgets."""

from __future__ import annotations

import os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import ContractError, content_hash
from .cutting_contracts import (
    make_document,
    same_original_occurrence,
    validate_cutting_document,
    validate_original_binding,
)
from .store import ArtifactStore, StoreError, now_iso, write_immutable_json


class CuttingStoreError(StoreError):
    """A cutting write or repair claim cannot be committed safely."""


def _same_budget(payload, identities, bindings):
    if (
        payload["occurrenceId"] in identities
        or payload.get("budgetOccurrenceId") in identities
    ):
        return True
    original = payload.get("originalBinding")
    return bool(
        original and any(same_original_occurrence(original, item) for item in bindings)
    )


@contextmanager
def _exclusive_lock(path: Path):
    """OS-owned advisory lock: process exit releases it without stale sentinels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class CuttingStore:
    """Sidecar evidence is not selection authority; CMap remains its owner."""

    def __init__(self, directory: Path, *, video_id: str, provider: str, clock=now_iso):
        self.directory = Path(directory)
        self.video_id = video_id
        self.provider = provider
        self.clock = clock
        self.ledger = ArtifactStore(self.directory / "repair-ledger.json", clock=clock)

    def head_hash(self) -> str | None:
        return self.ledger.head_hash() if self.ledger.path.exists() else None

    def save_document(self, document: dict[str, Any]) -> dict[str, str]:
        try:
            checked = validate_cutting_document(document)
            sha256 = content_hash(checked)
            locator = f"documents/{checked['documentType']}/{sha256}.json"
            write_immutable_json(self.directory / locator, checked)
            return {"locator": locator, "sha256": sha256}
        except (ContractError, OSError, StoreError) as exc:
            raise CuttingStoreError(str(exc)) from exc

    def load_document(self, reference: dict[str, str]) -> dict[str, Any]:
        import json

        try:
            path = (self.directory / reference["locator"]).resolve()
            if not path.is_relative_to(self.directory.resolve()):
                raise CuttingStoreError("cutting reference escapes evidence directory")
            document = json.loads(path.read_text(encoding="utf-8"))
            if content_hash(document) != reference["sha256"]:
                raise CuttingStoreError("cutting immutable reference hash mismatch")
            return validate_cutting_document(document)
        except (ContractError, OSError, ValueError, KeyError) as exc:
            raise CuttingStoreError(str(exc)) from exc

    def _snapshot(self) -> dict[str, Any]:
        if not self.ledger.path.exists():
            return {"reservations": [], "outcomes": []}
        ledger = self.ledger.load()
        if not ledger["revisions"]:
            return {"reservations": [], "outcomes": []}
        return deepcopy(ledger["revisions"][-1]["snapshot"])

    def reservations(
        self, occurrence_id: str, *, original_binding=None
    ) -> list[dict[str, Any]]:
        documents = [
            self.load_document(ref) for ref in self._snapshot()["reservations"]
        ]
        bindings = (
            [validate_original_binding(original_binding)] if original_binding else []
        )
        matched, remaining = [], list(documents)
        identities = {occurrence_id}
        while True:
            found = [
                doc
                for doc in remaining
                if _same_budget(doc["payload"], identities, bindings)
            ]
            if not found:
                return matched
            for doc in found:
                payload = doc["payload"]
                identities.update(
                    (
                        payload["occurrenceId"],
                        payload.get("budgetOccurrenceId", payload["occurrenceId"]),
                    )
                )
                if payload.get("originalBinding"):
                    bindings.append(payload["originalBinding"])
                matched.append(doc)
                remaining.remove(doc)

    def _initialize(self):
        self.ledger.initialize(
            artifact_type="cutting-ledger",
            artifact_id=f"{self.video_id}:cutting-repairs",
            video_id=self.video_id,
            provider=self.provider,
            timeline_domain="raw-source",
        )

    def _check_head(self, expected: str | None):
        actual = self.head_hash()
        if actual != expected:
            raise CuttingStoreError(
                f"cutting compare-and-swap failed: expected {expected}, actual {actual}"
            )

    def reserve_repair(
        self,
        *,
        occurrence_id: str,
        proposal_ref: dict[str, str],
        selection_hash: str,
        actor: str,
        expected_head_hash: str | None,
        original_binding: dict | None = None,
    ) -> dict[str, Any]:
        """Reserve before altering a selection; failure/crash never refunds a claim.

        ``occurrence_id`` is the original source/unit identity, not the current
        program time, policy hash or refined word boundary. Transport retries
        reuse this returned reservation and must not call this method again.
        """
        with _exclusive_lock(self.directory / ".repair-ledger.lock"):
            self._check_head(expected_head_hash)
            self._initialize()
            prior = self.reservations(occurrence_id, original_binding=original_binding)
            ordinal = len(prior) + 1
            if ordinal > 2:
                raise CuttingStoreError(
                    "two automatic selection repairs already reserved"
                )
            lineage = {}
            if original_binding:
                lineage = {
                    "originalBinding": validate_original_binding(original_binding),
                    "budgetOccurrenceId": prior[0]["payload"].get(
                        "budgetOccurrenceId", prior[0]["payload"]["occurrenceId"]
                    )
                    if prior
                    else occurrence_id,
                }
            document = make_document(
                "repair-reservation",
                {
                    "occurrenceId": occurrence_id,
                    "ordinal": ordinal,
                    "actor": actor,
                    "proposalRef": proposal_ref,
                    "selectionHash": selection_hash,
                    "reservedAt": self.clock(),
                    "status": "reserved",
                    **lineage,
                },
            )
            snapshot = self._snapshot()
            snapshot["reservations"].append(self.save_document(document))
            self.ledger.append_revision(
                snapshot=snapshot,
                actor=actor,
                reason=f"reserve selection repair {ordinal} for {occurrence_id}",
                expected_head_hash=expected_head_hash,
            )
            return document

    def record_result(
        self,
        reservation: dict[str, Any],
        *,
        status: str,
        result_ref: dict[str, str],
        actor: str,
        expected_head_hash: str,
    ) -> dict[str, Any]:
        """Append an outcome without mutating or refunding the original claim."""
        if status not in {"completed", "failed", "abandoned"}:
            raise CuttingStoreError("repair outcome must be terminal")
        with _exclusive_lock(self.directory / ".repair-ledger.lock"):
            self._check_head(expected_head_hash)
            original = validate_cutting_document(reservation, "repair-reservation")
            payload = original["payload"]
            if original not in self.reservations(payload["occurrenceId"]):
                raise CuttingStoreError("repair result has no committed reservation")
            snapshot = self._snapshot()
            for ref in snapshot["outcomes"]:
                existing = self.load_document(ref)["payload"]
                if (existing["occurrenceId"], existing["ordinal"]) == (
                    payload["occurrenceId"],
                    payload["ordinal"],
                ):
                    raise CuttingStoreError("repair already has a terminal outcome")
            outcome = make_document(
                "repair-reservation",
                {**payload, "status": status, "resultRef": result_ref},
            )
            snapshot["outcomes"].append(self.save_document(outcome))
            self.ledger.append_revision(
                snapshot=snapshot,
                actor=actor,
                reason=f"record {status} repair {payload['ordinal']}",
                expected_head_hash=expected_head_hash,
            )
            return outcome
