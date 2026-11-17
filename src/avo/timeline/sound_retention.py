"""Selected sound request/recovery closure, sharing the bounded motion ledger."""

from types import SimpleNamespace

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


class SoundRetention:
    def __init__(self, retained):
        self.retained = retained
        self.workspace = retained.workspace
        self.planning = SoundPlanningService(
            self.workspace, catalogue=SimpleNamespace(workspace=self.workspace)
        )
        self.application_service = _Application(self.planning)
        self.visited = set()

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
        if identity in self.visited:
            return
        self.visited.add(identity)
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
        if receipt["state"] == "committed":
            actual = self.retained.service._actual_committed(
                receipt, require_active=False
            )
            _require(
                actual == receipt["committedHeads"]
                and set(actual) == {"bmap", "tracks"},
                "committed sound history changed",
            )

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
            return False
        operation, _ = self.retained.read(path)
        operation = _sound_document(operation, "applicationOperation")
        self.application(operation["requestRef"], request_hash=marker["requestHash"])
        return True
