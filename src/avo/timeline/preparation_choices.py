"""Review source transcript alternatives without granting cut authority."""

from copy import deepcopy

from .contracts import content_hash, validate_document
from .cutting_contracts import make_document
from .cutting_store import CuttingStoreError
from .motion_metadata import METADATA_LIMITS, _check_budget
from .preparation_recovery import PreparationError

SCHEMA = "avo.preparation.schema.json"


def _target(service, request):
    frozen = service.store.load_document(request["requestRef"])
    if frozen["documentType"] != "speech-recovery-request":
        raise PreparationError("Evidence choice requires a retained recovery request")
    frozen = frozen["payload"]
    intervals = frozen["input"]["ranges"]
    if request["intervalIndex"] >= len(intervals):
        raise PreparationError("Evidence choice has an unknown source interval")
    result = None
    if request["resultRef"] is not None:
        document = service.store.load_document(request["resultRef"])
        result = document["payload"]
        if (
            document["documentType"] != "speech-recovery-result"
            or result["requestRef"] != request["requestRef"]
            or result["intervalIndex"] != request["intervalIndex"]
        ):
            raise PreparationError("Evidence choice changes its recovery result scope")
    return frozen, intervals[request["intervalIndex"]], result


def _require_current(service, request, frozen, result):
    choice = request["choice"]
    if choice == "original":
        service._source_context(frozen["input"])
    elif choice == "recovered":
        if (
            not result
            or result["status"] != "pending-review"
            or result["recovered"] is None
        ):
            raise PreparationError("Recovered evidence is unavailable, failed or stale")
        if not service._still_current(frozen, frozen["input"]):
            raise PreparationError(
                "Recovered evidence is stale: source/model inputs changed"
            )


def _view(service, reference, payload, frozen, result):
    choice = payload["input"]["choice"]
    eligible = False
    status = {
        "original": "selected",
        "recovered": "selected",
        "reject": "rejected",
        "defer": "deferred",
    }[choice]
    try:
        _require_current(service, payload["input"], frozen, result)
    except (OSError, ValueError, TypeError, KeyError):
        status = "stale"
    if choice == "recovered" and result:
        eligible = result["wordAnchorsEligible"]
    elif choice == "original":
        eligible = service._word_eligibility(
            service._analysis(frozen["input"]["analysisRef"])
        )
    return {
        "status": status,
        "choice": choice,
        "decisionRef": reference,
        "sourceRange": deepcopy(payload["sourceRange"]),
        "wordAnchorsEligible": eligible and status != "stale",
        "cutApproval": "not-granted",
    }


def decide_recovery(service, request):
    try:
        _check_budget(request, METADATA_LIMITS)
        validate_document(request, SCHEMA + "#/$defs/decideRequest")
        frozen, interval, result = _target(service, request)
        existing = service.store.recovery_decision(request["operationId"])
        if existing:
            if existing[1]["payload"]["requestHash"] != content_hash(request):
                raise PreparationError(
                    "Evidence decision operation changes request identity"
                )
            return _view(service, existing[0], existing[1]["payload"], frozen, result)
        _require_current(service, request, frozen, result)
        payload = {
            "input": deepcopy(request),
            "requestHash": content_hash(request),
            "sourceRange": deepcopy(interval),
            "knownResultRefs": service.store.overlapping_recovery_results(
                request["requestRef"], interval
            ),
            "decidedAt": service.store.clock(),
        }
        reference = service.store.record_recovery_decision(
            make_document("speech-recovery-decision", payload)
        )
        return _view(service, reference, payload, frozen, result)
    except (OSError, ValueError, TypeError, KeyError, CuttingStoreError) as error:
        raise PreparationError(str(error)) from error
