"""Verified selected motion evidence closure; generated review pages are caches."""

from __future__ import annotations

import hashlib
from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection
from avo.library.rules import safe_path

from .contracts import content_hash, validate_document
from .motion_authoring import MotionAuthoringService

MAX_FILES = 2000
MAX_TOTAL_BYTES = 64 * 1024 * 1024
SCHEMA = "avo.motion-proposal.schema.json"
COLLECTIONS = {
    "proposal": "proposals",
    "decision": "decisions",
    "applyRequest": "requests",
    "receipt": "receipts",
}
EVIDENCE = {
    "motion-proposal": "proposal",
    "motion-decision": "decision",
    "motion-application": "applyRequest",
}


class MotionRetentionError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise MotionRetentionError("Cannot retain selected motion evidence: " + message)


class _Retention:
    def __init__(self, workspace):
        self.workspace = workspace
        self.raw = workspace.raw_dir.resolve()
        self.service = MotionAuthoringService(workspace)
        self.documents = {}
        self.total = 0
        self.proposals = []

    def read(self, path, definition=None):
        relative = Path(path).relative_to(self.raw).as_posix()
        target = safe_path(self.raw, relative)
        if target not in self.documents:
            _require(len(self.documents) < MAX_FILES, "evidence file budget exceeded")
            value, raw = self.service._read(target)
            _require(isinstance(value, dict), "evidence must be a JSON object")
            self.total += len(raw)
            _require(self.total <= MAX_TOTAL_BYTES, "evidence byte budget exceeded")
            self.documents[target] = (value, hashlib.sha256(raw).hexdigest())
        value, digest = self.documents[target]
        if definition:
            validate_document(value, f"{SCHEMA}#/$defs/{definition}")
        return value, digest

    def reference(self, reference, definition):
        validate_document(reference, f"{SCHEMA}#/$defs/ref")
        expected = (
            self.raw
            / "edit/motion"
            / COLLECTIONS[definition]
            / (reference["sha256"] + ".json")
        )
        _require(
            reference["path"] == expected.relative_to(self.raw).as_posix(),
            "reference does not name its exact typed document",
        )
        value, digest = self.read(expected, definition)
        _require(digest == reference["sha256"], "selected evidence file hash changed")
        if definition in {"proposal", "decision"}:
            _require(
                value["provider"] == self.workspace.project["provider"]
                and value["videoId"] == self.workspace.video_id,
                "selected evidence belongs to another project",
            )
        return value

    def operation(self, operation, value, reference):
        identity = content_hash([operation, value["operationId"]])
        path = self.raw / "edit/motion/operations" / (identity + ".json")
        record, _ = self.read(path, "operationIntent")
        _require(
            record["operation"] == operation
            and record["operationId"] == value["operationId"]
            and record["resultRef"] == reference,
            "operation/result identity changed",
        )
        _require(
            record["requestHash"] == content_hash(record["request"]),
            "frozen operation request hash changed",
        )
        if value.get("requestHash"):
            _require(
                record["requestHash"] == value["requestHash"],
                "result request hash differs from operation",
            )
        _require(
            record["request"]["operation"] == operation
            and record["request"]["operationId"] == value["operationId"],
            "operation request identity changed",
        )

    def proposal(self, reference):
        value = self.reference(reference, "proposal")
        validate_editing_craft_selection(value["options"])
        self.operation(value.get("operation", "plan-propose"), value, reference)
        if value["directionRef"]:
            self.direction(value["directionRef"])
        if value["predecessor"]:
            digest = value["predecessor"]
            self.proposals.append(
                {"path": f"edit/motion/proposals/{digest}.json", "sha256": digest}
            )
        return value

    def direction(self, reference):
        root = self.raw / "edit/briefstart"
        path = self.raw / reference["path"]
        _require(
            path.is_relative_to(root) and path.suffix == ".json",
            "direction reference is not local authorial evidence",
        )
        value, digest = self.read(path)
        _require(digest == reference["sha256"], "frozen direction hash changed")
        _require(
            value.get("documentType") == "BriefSelection",
            "direction must bind its exact selected choice",
        )
        queue = [(path, None)]
        visited = set()
        while queue:
            selected, expected = queue.pop()
            if selected in visited:
                continue
            visited.add(selected)
            document = self.direction_document(selected, expected)
            references = [
                document[key]
                for key in ("briefRef", "decisionRef")
                if document.get(key)
            ]
            references.extend(document.get("sourceRefs", []))
            for item in references:
                queue.append((safe_path(root, item["path"]), item))

    def direction_document(self, path, reference):
        from avo.direction.rules import validate

        value, _ = self.read(path)
        kind = value.get("documentType")
        _require(
            kind
            in {
                "BriefSelection",
                "ProjectBriefVersion",
                "CreatorDecision",
                "FrozenBriefSource",
            },
            "unsupported authorial direction dependency",
        )
        validate(kind, value)
        if reference:
            _require(
                value["id"] == reference["id"]
                and value["documentHash"] == reference["documentHash"],
                "selected direction document identity changed",
            )
        return value

    def decision(self, reference):
        value = self.reference(reference, "decision")
        proposal_ref = {
            "path": f"edit/motion/proposals/{value['proposalHash']}.json",
            "sha256": value["proposalHash"],
        }
        proposal = self.reference(proposal_ref, "proposal")
        _require(
            value["requestId"] == proposal["requestId"],
            "decision request differs from proposal",
        )
        identities = {item["itemId"] for item in proposal["items"]}
        selected = [item["itemId"] for item in value["dispositions"]]
        _require(
            len(selected) == len(set(selected)) and set(selected) <= identities,
            "decision item identity differs",
        )
        self.operation("plan-select", value, reference)
        self.proposals.append(proposal_ref)
        return value

    def receipt(self, reference):
        value = self.reference(reference, "receipt")
        request = self.reference(value["requestRef"], "applyRequest")
        self.service._verify_receipt_intent(request, value)
        self.decision(value["decisionRef"])
        self.proposals.append(value["proposalRef"])
        for name, prepared in value["prepared"].items():
            self.workspace.store(name)._validate_revision(prepared)
        if value["state"] == "committed":
            self.service._verify_committed_receipt(value)
        return value

    def selection(self, value):
        validate_document(value, f"{SCHEMA}#/$defs/selectionRef")
        decision = self.decision(value["decisionRef"])
        _require(
            decision["proposalHash"] == value["proposalRef"]["sha256"]
            and decision["requestId"] == value["requestId"],
            "selected decision/proposal/request differ",
        )
        self.proposals.append(value["proposalRef"])
        if value.get("receiptRef"):
            receipt = self.receipt(value["receiptRef"])
            _require(
                receipt["proposalRef"] == value["proposalRef"]
                and receipt["decisionRef"] == value["decisionRef"],
                "selected application refers to another choice",
            )
            self.application(receipt["operationId"], receipt["requestHash"])

    def application(self, operation_id, request_hash):
        path = (
            self.raw
            / "edit/motion/applications"
            / content_hash(operation_id)
            / "current.json"
        )
        selector, _ = self.read(path)
        receipt = self.receipt(selector)
        _require(
            receipt["operationId"] == operation_id
            and receipt["requestHash"] == request_hash,
            "application selector changed request identity",
        )
        self.apply_operation(receipt)

    def apply_operation(self, receipt):
        request = self.reference(receipt["requestRef"], "applyRequest")
        operation = request["operation"]
        identity = content_hash([operation, receipt["operationId"]])
        path = self.raw / "edit/motion/operations" / (identity + ".json")
        if not path.exists() and not path.is_symlink():
            return  # Staging can be interrupted before its operation log is written.
        record, _ = self.read(path, "operationIntent")
        self.operation(operation, receipt, record["resultRef"])
        staged = self.receipt(record["resultRef"])
        _require(
            staged["operationId"] == receipt["operationId"]
            and staged["requestHash"] == receipt["requestHash"],
            "staged operation changed application identity",
        )

    def canonical_index(self, store, name):
        if not store.path.exists() and not store.path.is_symlink():
            return None
        index, _ = self.read(store.path)
        if not index.get("revisionRefs") and index.get("headRevisionId") is None:
            # Preserve unclaimed legacy metadata as bytes, without adopting it
            # as a canonical index or granting any rendering/approval authority.
            return None
        store._validate_index(index)
        _require(
            index["artifactType"] == name, "canonical index changes artifact owner"
        )
        return index

    def canonical(self):
        for name in ("cmap", "bmap", "tracks", "animation", "sync-map"):
            store = self.workspace.store(name)
            index = self.canonical_index(store, name)
            if index is None:
                continue
            for reference in index["revisionRefs"]:
                revision, _ = self.read(store.timeline_dir / reference["path"])
                store._validate_revision(revision)
                _require(
                    revision["revisionId"] == reference["revisionId"]
                    and revision["contentSha256"] == reference["contentSha256"]
                    and revision["artifactType"] == name,
                    "canonical revision reference identity changed",
                )
                for evidence in revision.get("inputEvidenceRefs", []):
                    definition = EVIDENCE.get(evidence.get("kind"))
                    if definition:
                        self.authorial_evidence(evidence, definition)

    def authorial_evidence(self, evidence, definition):
        reference = {key: evidence[key] for key in ("path", "sha256")}
        if definition == "proposal":
            self.proposals.append(reference)
        elif definition == "decision":
            self.decision(reference)
        else:
            request = self.reference(reference, definition)
            self.application(request["operationId"], content_hash(request))

    def run_record(self):
        path = self.workspace.pipeline_run_path
        if path.exists() or path.is_symlink():
            run, _ = self.read(path)
            validate_document(run, "avo.pipeline-run.schema.json")
            extensions = run.get("extensions") or {}
            frozen = (run.get("executionChoices") or {}).get("editingCraft")
            self.frozen_requests(
                ([frozen] if frozen else [])
                + extensions.get("editingCraftRequestHistory", [])
            )
            selected = extensions.get("motionProposalSelection")
            history = extensions.get("motionProposalSelectionHistory", [])
            if selected:
                self.selection(selected)
            for item in history:
                self.selection(item)

    def frozen_requests(self, requests):
        for frozen in requests:
            validate_editing_craft_selection(frozen["selection"])
            if frozen["directionRef"]:
                self.direction(frozen["directionRef"])

    def pending(self):
        pending = self.workspace.timeline_dir / "motion-application.pending.json"
        if pending.exists() or pending.is_symlink():
            marker, _ = self.read(pending)
            _require(
                isinstance(marker, dict)
                and set(marker) == {"operationId", "requestHash"},
                "invalid pending application marker",
            )
            self.application(marker["operationId"], marker["requestHash"])

    def run(self):
        self.canonical()
        self.run_record()
        self.pending()
        visited = set()
        while self.proposals:
            reference = self.proposals.pop()
            if reference["sha256"] not in visited:
                visited.add(reference["sha256"])
                self.proposal(reference)
        return sorted(self.documents)


def retained_motion_files(workspace):
    """Bind the verified closure to exact bytes for later bundle fingerprinting."""
    try:
        retained = _Retention(workspace)
        retained.run()
        return {path: digest for path, (_, digest) in retained.documents.items()}
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if isinstance(error, MotionRetentionError):
            raise
        raise MotionRetentionError(
            f"Cannot retain selected motion evidence: {error}"
        ) from error


def retained_motion_paths(workspace):
    """Read only selected/history/recovery authorial dependencies, never media."""
    return sorted(retained_motion_files(workspace))
