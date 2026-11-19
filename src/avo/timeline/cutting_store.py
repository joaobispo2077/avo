"""Immutable cutting evidence and source-stable, crash-consumed repair budgets."""

from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import ContractError, content_hash, validate_document
from .cutting_contracts import (
    make_document,
    same_original_occurrence,
    source_interval,
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
def _exclusive_lock(path: Path, *, blocking=True):
    """OS-owned advisory lock: process exit releases it without stale sentinels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(
                    stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1
                )
            except OSError as error:
                if not blocking and error.errno in {errno.EACCES, errno.EAGAIN}:
                    raise BlockingIOError(
                        "recovery interval is already running"
                    ) from error
                raise
        else:
            import fcntl

            fcntl.flock(
                stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            )
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

    def recovery_request(self, operation_id):
        for reference in self._snapshot().get("preparationRequests", []):
            document = self.load_document(reference)
            if document["payload"]["input"]["operationId"] == operation_id:
                return reference, document
        return None

    def _append_preparation(self, snapshot, actor, reason):
        self._initialize()
        self.ledger.append_revision(
            snapshot=snapshot,
            actor=actor,
            reason=reason,
            expected_head_hash=self.head_hash(),
        )

    def register_recovery(self, document):
        document = validate_cutting_document(document, "speech-recovery-request")
        request = document["payload"]["input"]
        with _exclusive_lock(self.directory / ".repair-ledger.lock"):
            existing = self.recovery_request(request["operationId"])
            if existing:
                if (
                    existing[1]["payload"]["requestHash"]
                    != document["payload"]["requestHash"]
                ):
                    raise CuttingStoreError(
                        "recovery operation ID changes request identity"
                    )
                return existing[0]
            snapshot = self._snapshot()
            reference = self.save_document(document)
            snapshot.setdefault("preparationRequests", []).append(reference)
            self._append_preparation(
                snapshot, request["actor"], "register selected speech recovery"
            )
            return reference

    def recovery_attempt(self, request_ref, interval_index):
        for reference in self._snapshot().get("preparationAttempts", []):
            document = self.load_document(reference)
            payload = document["payload"]
            if (
                payload["requestRef"] == request_ref
                and payload["intervalIndex"] == interval_index
            ):
                return reference, document
        return None

    @contextmanager
    def recovery_interval_lock(self, request_ref, interval_index):
        identity = content_hash([request_ref, interval_index])
        with _exclusive_lock(
            self.directory / "preparation-locks" / (identity + ".lock"), blocking=False
        ):
            yield

    @staticmethod
    def _recovery_budget_source(binding):
        return {
            "sha256": binding["sourceRef"]["sha256"],
            "streamIndex": binding["routing"]["streamIndex"],
            "channels": sorted(binding["routing"]["channels"]),
        }

    def _prior_recoveries(self, source, interval):
        _, first, end = source_interval(interval)
        found = []
        for reference in self._snapshot().get("preparationAttempts", []):
            payload = self.load_document(reference)["payload"]
            if payload["budgetSource"] != source:
                continue
            _, start, last = source_interval(payload["sourceRange"])
            if max(first, start) < min(end, last):
                found.append(reference)
        return found

    def claim_recovery(self, request_ref, interval_index):
        with _exclusive_lock(self.directory / ".repair-ledger.lock"):
            if request_ref not in self._snapshot().get("preparationRequests", []):
                raise CuttingStoreError(
                    "recovery request has no committed registration"
                )
            existing = self.recovery_attempt(request_ref, interval_index)
            if existing:
                return existing[0], existing[1], False
            frozen = self.load_document(request_ref)["payload"]
            request = frozen["input"]
            if type(interval_index) is not int or not 0 <= interval_index < len(
                request["ranges"]
            ):
                raise CuttingStoreError(
                    "recovery interval index is outside its request"
                )
            interval = request["ranges"][interval_index]
            source = self._recovery_budget_source(frozen["binding"])
            prior = self._prior_recoveries(source, interval)
            limit = request["selection"]["effective"]["speechRecovery"][
                "maxAttemptsPerInterval"
            ]
            if len(prior) >= limit:
                raise CuttingStoreError("speech recovery attempt budget is exhausted")
            document = make_document(
                "speech-recovery-attempt",
                {
                    "requestRef": request_ref,
                    "intervalIndex": interval_index,
                    "sourceRange": interval,
                    "sourceRef": frozen["binding"]["sourceRef"],
                    "budgetSource": source,
                    "ordinal": len(prior) + 1,
                    "actor": request["actor"],
                    "reservedAt": self.clock(),
                },
            )
            reference = self.save_document(document)
            snapshot = self._snapshot()
            snapshot.setdefault("preparationAttempts", []).append(reference)
            self._append_preparation(
                snapshot,
                request["actor"],
                "claim bounded speech recovery before inference",
            )
            return reference, document, True

    def recovery_result(self, attempt_ref):
        import json

        validate_document(attempt_ref, "avo.cutting.schema.json#/$defs/artifactRef")
        if attempt_ref not in self._snapshot().get("preparationAttempts", []):
            raise CuttingStoreError("recovery result lookup has no committed attempt")
        path = (
            self.directory / "preparation-results" / (attempt_ref["sha256"] + ".json")
        )
        if not path.exists():
            return None
        with path.open("rb") as stream:
            data = stream.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise CuttingStoreError("speech recovery result exceeds its byte budget")
        document = validate_cutting_document(json.loads(data), "speech-recovery-result")
        if document["payload"]["attemptRef"] != attempt_ref:
            raise CuttingStoreError("speech recovery result changed its owning attempt")
        reference = {
            "locator": path.relative_to(self.directory).as_posix(),
            "sha256": content_hash(document),
        }
        return reference, document

    def record_recovery_result(self, document):
        document = validate_cutting_document(document, "speech-recovery-result")
        payload = document["payload"]
        with _exclusive_lock(self.directory / ".repair-ledger.lock"):
            attempt_ref = payload["attemptRef"]
            if attempt_ref not in self._snapshot().get("preparationAttempts", []):
                raise CuttingStoreError("recovery result has no committed attempt")
            attempt = self.load_document(attempt_ref)["payload"]
            if any(
                payload[key] != attempt[key]
                for key in ("requestRef", "intervalIndex", "sourceRange")
            ):
                raise CuttingStoreError("recovery result changed its reserved scope")
            frozen = self.load_document(payload["requestRef"])["payload"]
            if payload["originalAnalysisRef"] != frozen["input"]["analysisRef"]:
                raise CuttingStoreError("recovery result changed its original analysis")
            locator = "preparation-results/" + attempt_ref["sha256"] + ".json"
            # One deterministic immutable result is durable before ledger publication.
            write_immutable_json(self.directory / locator, document)
            reference = {"locator": locator, "sha256": content_hash(document)}
            snapshot = self._snapshot()
            references = snapshot.setdefault("preparationResults", [])
            if reference not in references:
                references.append(reference)
                self._append_preparation(
                    snapshot, attempt["actor"], "retain speech recovery pending review"
                )
            return reference

    def recovery_decision(self, operation_id):
        for reference in self._snapshot().get("preparationDecisions", []):
            document = self.load_document(reference)
            validate_cutting_document(document, "speech-recovery-decision")
            if document["payload"]["input"]["operationId"] == operation_id:
                return reference, document
        return None

    def active_recovery_decisions(self):
        records = [
            (reference, self.load_document(reference))
            for reference in self._snapshot().get("preparationDecisions", [])
        ]
        superseded = {
            content_hash(reference)
            for _, document in records
            for reference in document["payload"]["input"]["expectedDecisionRefs"]
        }
        return [
            (reference, document["payload"])
            for reference, document in records
            if content_hash(reference) not in superseded
        ]

    def recovery_overlaps(
        self, request_ref, interval, other_request_ref, other_interval
    ):
        left = self.load_document(request_ref)["payload"]["binding"]
        right = self.load_document(other_request_ref)["payload"]["binding"]
        if self._recovery_budget_source(left) != self._recovery_budget_source(right):
            return False
        _, first, end = source_interval(interval)
        _, start, last = source_interval(other_interval)
        return max(first, start) < min(end, last)

    def overlapping_recovery_decisions(self, request_ref, interval):
        return [
            (reference, payload)
            for reference, payload in self.active_recovery_decisions()
            if self.recovery_overlaps(
                request_ref,
                interval,
                payload["input"]["requestRef"],
                payload["sourceRange"],
            )
        ]

    def overlapping_recovery_results(self, request_ref, interval):
        references = []
        for reference in self._snapshot().get("preparationResults", []):
            payload = self.load_document(reference)["payload"]
            if self.recovery_overlaps(
                request_ref, interval, payload["requestRef"], payload["sourceRange"]
            ):
                references.append(reference)
        return references

    def record_recovery_decision(self, document):
        document = validate_cutting_document(document, "speech-recovery-decision")
        payload, request = document["payload"], document["payload"]["input"]
        if payload["requestHash"] != content_hash(request):
            raise CuttingStoreError("recovery decision changes request identity")
        with _exclusive_lock(self.directory / ".repair-ledger.lock"):
            existing = self.recovery_decision(request["operationId"])
            if existing:
                if existing[1]["payload"]["requestHash"] != payload["requestHash"]:
                    raise CuttingStoreError(
                        "recovery decision operation changes request identity"
                    )
                return existing[0]
            self._check_head(request["expectedLedgerHash"])
            self._check_recovery_decision_scope(payload)
            reference = self.save_document(document)
            snapshot = self._snapshot()
            snapshot.setdefault("preparationDecisions", []).append(reference)
            self._append_preparation(
                snapshot,
                request["actor"],
                "review source transcript alternatives without approving cuts",
            )
            return reference

    def _check_recovery_decision_scope(self, payload):
        request = payload["input"]
        if request["requestRef"] not in self._snapshot().get("preparationRequests", []):
            raise CuttingStoreError("recovery decision has no retained request")
        frozen = self.load_document(request["requestRef"])["payload"]
        intervals = frozen["input"]["ranges"]
        if (
            request["intervalIndex"] >= len(intervals)
            or payload["sourceRange"] != intervals[request["intervalIndex"]]
        ):
            raise CuttingStoreError("recovery decision changes its source interval")
        active = self.overlapping_recovery_decisions(
            request["requestRef"], payload["sourceRange"]
        )
        if {content_hash(ref) for ref, _ in active} != {
            content_hash(ref) for ref in request["expectedDecisionRefs"]
        }:
            raise CuttingStoreError(
                "recovery decision predecessor conflicts with current choices"
            )
        results = self.overlapping_recovery_results(
            request["requestRef"], payload["sourceRange"]
        )
        if payload["knownResultRefs"] != results or (
            request["resultRef"] is not None and request["resultRef"] not in results
        ):
            raise CuttingStoreError("recovery decision alternatives changed")
        self._check_recovery_choice_result(request)

    def _check_recovery_choice_result(self, request):
        if request["resultRef"] is None:
            if request["choice"] == "recovered":
                raise CuttingStoreError("recovered choice requires its exact result")
            return
        document = self.load_document(request["resultRef"])
        payload = document["payload"]
        if (
            document["documentType"] != "speech-recovery-result"
            or payload["requestRef"] != request["requestRef"]
            or payload["intervalIndex"] != request["intervalIndex"]
        ):
            raise CuttingStoreError("recovery choice result changes its source scope")
        if request["choice"] == "recovered" and (
            payload["status"] != "pending-review" or payload["recovered"] is None
        ):
            raise CuttingStoreError("recovery choice result is unavailable")
