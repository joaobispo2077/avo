"""Bounded typed craft requests; preferences never grant timeline authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from avo.editing_craft import EditingCraftError
from avo.timeline.contracts import ContractError, content_hash, validate_document

MAX_REQUEST_BYTES = 1024 * 1024
OPTIONS_OPERATIONS = ("options-show", "options-set", "options-reset")
OPERATION_EFFECTS = {
    "options-show": "metadata-read",
    "options-set": "preference-write",
    "options-reset": "preference-write",
}


class CraftRequestError(EditingCraftError):
    """A request failed before execution or preference mutation."""


def _invalid(message: str, *, field: str = "request") -> CraftRequestError:
    return CraftRequestError(
        "CRAFT_REQUEST_INVALID",
        message,
        field=field,
        remediation="Supply a bounded typed request for the selected operation.",
    )


def validate_craft_request(value: Any, *, operation: str) -> dict[str, Any]:
    """Validate exact selected scope without accepting a caller-chosen owner."""
    try:
        validate_document(value, "avo.editing-craft-request.schema.json")
    except ContractError as error:
        raise _invalid(str(error)) from error
    if operation not in OPTIONS_OPERATIONS[1:] or value["operation"] != operation:
        raise _invalid(
            "Request operation differs from the selected command.", field="operation"
        )
    return deepcopy(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate request property: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def read_craft_request(path: Path | str, *, expected_sha256: str | None = None) -> Any:
    """Read a bounded request, optionally bound to exact confirmation bytes."""
    path = Path(path)
    if not path.is_absolute():
        raise _invalid("Request path must be absolute.", field="requestPath")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise _invalid("Request exceeds the 1 MiB input budget.")
        if (
            expected_sha256 is not None
            and hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise _invalid("Request changed after confirmation.")
        value = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (OSError, ValueError, RecursionError) as error:
        if isinstance(error, CraftRequestError):
            raise
        raise _invalid(f"Cannot read request: {error}") from error
    return value


def load_craft_request(path: Path | str, *, operation: str) -> dict[str, Any]:
    return validate_craft_request(read_craft_request(path), operation=operation)


def options_result(result: dict, request: dict | None = None) -> dict:
    """Describe the actual operation; this metadata creates no new authority."""
    operation = result["operation"]
    value = {
        **result,
        "status": "inspected" if request is None else "updated",
        "operationId": request["operationId"] if request else None,
        "effect": OPERATION_EFFECTS[operation],
        "inputBasis": request["expectedBasis"] if request else {},
        "coverage": {"kind": "preferences", "complete": True},
        "warnings": [],
        "blockers": [],
        "allowedNextActions": list(OPTIONS_OPERATIONS),
    }
    if request:
        value.update(
            actor=request["actor"],
            reason=request["reason"],
            requestHash=content_hash(request),
        )
    validate_document(value, "avo.editing-craft-result.schema.json")
    return value
