"""Selected sound request/recovery closure, sharing the bounded motion ledger."""

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

from avo.sfx_contracts import MAX_DOCUMENT_BYTES as MAX_CATALOGUE_BYTES
from avo.sfx_contracts import _hash, _validate_entries

from .contracts import content_hash, validate_document
from .sound_application import _Application
from .sound_choices import _sound_document
from .sound_planning import SoundPlanningService

COLLECTIONS = {
    "proposal": "proposals",
    "applyRequest": "requests",
    "applicationReceipt": "receipts",
}


def _require(condition, message):
    if not condition:
        raise ValueError("Cannot retain selected sound evidence: " + message)


def _catalogue_bytes(path):
    limit = MAX_CATALOGUE_BYTES
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, "catalogue metadata exceeds its 16 MiB byte budget")
    return json.loads(raw), raw


class SoundRetention:
    def __init__(self, retained):
        self.retained = retained
        self.workspace = retained.workspace
        self.planning = SoundPlanningService(
            self.workspace, catalogue=SimpleNamespace(workspace=self.workspace)
        )
        self.application_service = _Application(self.planning)
        self.visited = set()
        self.generations = {}
        self.applications = {}

    def reference(self, reference, definition):
        validate_document(reference, "avo.motion-proposal.schema.json#/$defs/ref")
        expected = self.planning._path(COLLECTIONS[definition], reference["sha256"])
        _require(
            reference["path"]
            == expected.relative_to(self.workspace.raw_dir).as_posix(),
            "reference does not name its exact typed sound document",
        )
        value, digest = self.retained.read(expected)
        _require(digest == reference["sha256"], "selected sound evidence hash changed")
        return _sound_document(value, definition)

    def proposal(self, reference):
        if reference["sha256"] in self.visited:
            return
        self.visited.add(reference["sha256"])
        value = self.reference(reference, "proposal")
        shown = self.planning.load(reference["sha256"])
        _require(
            shown["proposalRef"] == reference,
            "selected sound proposal reference changed",
        )
        identity = content_hash(["propose", value["operationId"]])
        self.retained.read(self.planning._path("operations", identity))
        self.generation(value["generationId"])
        if value["directionRef"]:
            self.retained.direction(value["directionRef"])

    def application(self, reference, *, request_hash=None):
        request = self.reference(reference, "applyRequest")
        expected = content_hash(request)
        _require(
            request_hash is None or expected == request_hash,
            "pending sound request identity changed",
        )
        identity = content_hash(["apply", request["operationId"]])
        if identity in self.applications:
            saved = self.applications[identity]
            _require(
                saved["requestRef"] == reference and saved["requestHash"] == expected,
                "repeated sound operation changes its request identity",
            )
            return saved
        operation, _ = self.retained.read(self.planning._path("operations", identity))
        operation = _sound_document(operation, "applicationOperation")
        _require(
            operation["requestRef"] == reference
            and operation["requestHash"] == expected,
            "sound operation request identity changed",
        )
        initial = self.reference(operation["initialReceiptRef"], "applicationReceipt")
        pointer, _ = self.retained.read(self.planning._path("applications", identity))
        receipt = self.reference(pointer, "applicationReceipt")
        self.application_service._verify_recipe(request, receipt, initial)
        _require(
            receipt["requestRef"] == reference and receipt["requestHash"] == expected,
            "sound receipt request identity changed",
        )
        self.receipt_history(request, receipt, initial)
        self.proposal(receipt["proposalRef"])
        self.selected_entries(request, receipt)
        if receipt["state"] == "committed":
            actual = self.retained.service._actual_committed(
                receipt, require_active=False
            )
            _require(
                actual == receipt["committedHeads"]
                and set(actual) == {"bmap", "tracks"},
                "committed sound history changed",
            )
        self.applications[identity] = receipt
        return receipt

    def generation(self, identity):
        if identity is None:
            return None
        if identity in self.generations:
            return self.generations[identity]
        path = (
            self.workspace.raw_dir
            / "edit/sfx-catalog/generations"
            / (identity + ".json")
        )
        value, _ = self.retained.read(path, reader=_catalogue_bytes)
        validate_document(value, "avo.sfx-catalog.schema.json")
        _require(
            value["generationId"] == identity
            and _hash(value, "generationId") == identity,
            "selected catalogue generation hash changed",
        )
        _validate_entries(value["entries"])
        self.generations[identity] = value
        return value

    def selected_entries(self, request, receipt):
        generation = self.generation(request["expectedGeneration"])
        entries = (
            {}
            if generation is None
            else {entry["entryId"]: entry for entry in generation["entries"]}
        )
        for choice in receipt["choices"]:
            entry = choice["sourceEntry"]
            if entry is not None:
                _require(
                    entries.get(entry["entryId"]) == entry,
                    "selected source entry differs from its exact catalogue generation",
                )

    def current_generation(self):
        path = self.workspace.raw_dir / "edit/sfx-catalog/current.json"
        if not path.exists() and not path.is_symlink():
            return
        value, _ = self.retained.read(path)
        _require(
            set(value) == {"schemaVersion", "generationId"}
            and value["schemaVersion"] == "1.0.0",
            "invalid pending sound catalogue selector",
        )
        validate_document(
            value["generationId"], "avo.sfx-catalog.schema.json#/$defs/sha"
        )
        self.generation(value["generationId"])

    def receipt_history(self, request, receipt, initial):
        seen = set()
        while receipt["previousReceiptRef"]:
            reference = receipt["previousReceiptRef"]
            _require(
                reference["sha256"] not in seen,
                "sound receipt history contains a cycle",
            )
            seen.add(reference["sha256"])
            receipt = self.reference(reference, "applicationReceipt")
            self.application_service._verify_recipe(request, receipt, initial)
        _require(
            receipt == initial,
            "sound receipt history does not reach its staged operation",
        )

    def pending(self, marker):
        identity = content_hash(["apply", marker["operationId"]])
        path = self.planning._path("operations", identity)
        if not path.exists() and not path.is_symlink():
            selector = self.planning._path("applications", identity)
            if not selector.exists() and not selector.is_symlink():
                return False
            receipt = self.application_selector(selector)
            _require(
                receipt["requestHash"] == marker["requestHash"],
                "pending staged sound request changed",
            )
            self.current_generation()
            return True
        operation, _ = self.retained.read(path)
        operation = _sound_document(operation, "applicationOperation")
        receipt = self.application(
            operation["requestRef"], request_hash=marker["requestHash"]
        )
        if receipt["state"] != "committed":
            self.current_generation()
        return True

    def load_applications(self):
        from .motion_retention import MAX_FILES

        root = self.planning._path("applications", "0" * 64).parent
        if not root.exists() and not root.is_symlink():
            return
        with os.scandir(root) as entries:
            for count, entry in enumerate(entries):
                _require(
                    count < MAX_FILES, "sound application selector budget exceeded"
                )
                if not entry.name.endswith(".json"):
                    continue
                _require(
                    re.fullmatch(r"[a-f0-9]{64}\.json", entry.name) is not None,
                    "invalid sound application selector name",
                )
                receipt = self.application_selector(Path(entry.path))
                if receipt["state"] != "committed":
                    self.current_generation()

    def application_selector(self, path):
        pointer, _ = self.retained.read(path)
        receipt = self.reference(pointer, "applicationReceipt")
        request = self.reference(receipt["requestRef"], "applyRequest")
        identity = content_hash(["apply", request["operationId"]])
        _require(
            path == self.planning._path("applications", identity),
            "sound application selector changes operation identity",
        )
        operation = self.planning._path("operations", identity)
        if operation.exists() or operation.is_symlink():
            return self.application(receipt["requestRef"])
        self._orphaned_stage(request, receipt)
        self.applications[identity] = receipt
        return receipt

    def _orphaned_stage(self, request, receipt):
        _require(
            receipt["requestHash"] == content_hash(request),
            "staged sound request identity changed",
        )
        self.application_service._verify_recipe(request, receipt, receipt)
        _require(
            not self.retained.service._actual_committed(receipt, require_active=False),
            "staged sound lost its published operation record",
        )
        self.proposal(receipt["proposalRef"])
        self.selected_entries(request, receipt)
