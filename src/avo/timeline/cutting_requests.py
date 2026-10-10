"""Validate external cutting requests separately from immutable evidence envelopes."""

from copy import deepcopy

from .contracts import ContractError, validate_document
from .cutting_contracts import validate_source_range


def _unique_decisions(request):
    identities = [item["occurrenceId"] for item in request.get("decisions", [])]
    if len(identities) != len(set(identities)):
        raise ContractError("a decision request cannot repeat an occurrence")


def validate_cutting_request(request: dict, operation: str = "analyze") -> dict:
    if operation not in {"analyze", "decide"}:
        raise ContractError("unknown cutting request operation")
    definition = "analyzeRequest" if operation == "analyze" else "decisionRequest"
    validate_document(request, "avo.cutting.schema.json#/$defs/" + definition)
    if "targetDurationMs" in request and type(request["targetDurationMs"]) is not int:
        raise ContractError("targetDurationMs must be an integer")
    rate = request.get("frameRate") or {}
    if any(type(value) is not int for value in rate.values()):
        raise ContractError("frameRate clock must contain integers")
    for unit in request.get("editorialUnits", []):
        validate_source_range(unit["sourceRange"])
    _unique_decisions(request)
    return deepcopy(request)
