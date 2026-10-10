"""Versioned cutting evidence contracts; these documents do not own selections."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from typing import Any

from .contracts import ContractError, content_hash, validate_document


def validate_source_range(value: dict[str, Any]) -> dict[str, Any]:
    validate_document(value, "avo.cutting.schema.json#/$defs/sourceRange")
    values = (
        value["startTicks"],
        value["endTicksExclusive"],
        value["timebase"]["num"],
        value["timebase"]["den"],
    )
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        raise ContractError("source clock ticks and timebase must be integers")
    if value["endTicksExclusive"] <= value["startTicks"]:
        raise ContractError("source range must be nonempty and half-open")
    return deepcopy(value)


def source_interval(value: dict[str, Any]) -> tuple[str, Fraction, Fraction]:
    """Resolve a validated source clock once without floating-point conversion."""
    interval = validate_source_range(value)
    base = interval["timebase"]
    scale = Fraction(base["num"], base["den"])
    return (
        interval["sourceId"],
        interval["startTicks"] * scale,
        interval["endTicksExclusive"] * scale,
    )


def validate_original_binding(value: dict[str, Any]) -> dict[str, Any]:
    validate_document(value, "avo.cutting.schema.json#/$defs/originalBinding")
    validate_source_range(value["sourceRange"])
    return deepcopy(value)


def same_original_occurrence(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Ambiguous refined/renamed overlap shares a budget rather than resetting it."""
    if left["sourceSha256"] != right["sourceSha256"]:
        return False
    source, first, last = source_interval(left["sourceRange"])
    other, start, end = source_interval(right["sourceRange"])
    return source == other and (
        content_hash(left["unitAnchor"]) == content_hash(right["unitAnchor"])
        or max(first, start) < min(last, end)
    )


def selection_graph_hash(snapshot: dict[str, Any]) -> str:
    """Bind selected originals without circular evidence-reference metadata."""
    return content_hash(
        {
            key: value
            for key, value in snapshot.items()
            if key not in {"cuttingRef", "protectionRef"}
        }
    )


def occurrence_id(
    source_sha256: str, source_id: str, unit_anchor: dict[str, Any]
) -> str:
    """Anchor identity in the original source, independent of edited clocks."""
    validate_document(source_sha256, "avo.cutting.schema.json#/$defs/sha256")
    if not source_id or not unit_anchor:
        raise ContractError("occurrence requires source and stable unit anchor")
    return (
        "occ-"
        + content_hash(
            {
                "sourceSha256": source_sha256,
                "sourceId": source_id,
                "unitAnchor": unit_anchor,
            }
        )[:24]
    )


def _validate_ranges(value: Any) -> None:
    if isinstance(value, dict):
        if {"sourceId", "startTicks", "endTicksExclusive", "timebase"} <= value.keys():
            validate_source_range(value)
        for child in value.values():
            _validate_ranges(child)
    elif isinstance(value, list):
        for child in value:
            _validate_ranges(child)


def validate_cutting_document(
    document: dict[str, Any], kind: str | None = None
) -> dict[str, Any]:
    validate_document(document, "avo.cutting.schema.json")
    if kind is not None and document["documentType"] != kind:
        raise ContractError("cutting document type mismatch")
    expected = content_hash(
        {key: value for key, value in document.items() if key != "documentHash"}
    )
    if document["documentHash"] != expected:
        raise ContractError("cutting document hash mismatch")
    _validate_ranges(document["payload"])
    return deepcopy(document)


def make_document(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    document = {
        "schemaVersion": "1.0.0",
        "documentType": kind,
        "payload": deepcopy(payload),
    }
    document["documentHash"] = content_hash(document)
    return validate_cutting_document(document, kind)


def selected_source_range(segment: dict) -> dict:
    return {
        "sourceId": segment["sourceId"],
        "startTicks": segment["in"]["ticks"],
        "endTicksExclusive": segment["out"]["ticks"],
        "timebase": segment["in"]["timebase"],
    }
