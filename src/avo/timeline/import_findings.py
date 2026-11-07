"""Bounded raw element accounting; reconstructed means preserved canonical state."""

from __future__ import annotations

import hashlib
from collections import Counter

from . import otio_import
from .contracts import canonical_json_bytes

MAX_ELEMENTS = 2048
MAX_FINDINGS = 2048
MAX_DETAIL_BYTES = 8 * 1024 * 1024
_RESERVED_BYTES = 2048
_DISPOSITIONS = ("reconstructed", "reference-metadata", "unresolved", "unsupported")
_TREATMENTS = {"Effect", "TimeEffect", "LinearTimeWarp", "FreezeFrame", "Transition"}
_COMPOSITIONS = {"Stack", "Timeline", "SerializableCollection"}


def _content_nodes(value, pointer):
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            if key != "metadata":
                yield from _content_nodes(child, otio_import._pointer(pointer, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _content_nodes(child, otio_import._pointer(pointer, index))


def _children(value):
    if not isinstance(value, dict) or not isinstance(value.get("children"), list):
        return []
    return value["children"]


def _direct_scopes(selected, pointer):
    root_stack = otio_import._pointer(pointer, "tracks")
    track_base = otio_import._pointer(root_stack, "children")
    tracks, children = set(), set()
    for index, track in enumerate(_children(selected.get("tracks"))):
        if not isinstance(track, dict) or track.get("OTIO_SCHEMA") != "Track.1":
            continue
        location = otio_import._pointer(track_base, index)
        tracks.add(location)
        child_base = otio_import._pointer(location, "children")
        children.update(
            otio_import._pointer(child_base, index)
            for index, _ in enumerate(_children(track))
        )
    return {
        "timeline": pointer,
        "rootStack": root_stack,
        "tracks": tracks,
        "children": children,
    }


def _parent_treatment(node, kind):
    return bool(node.get("effects")) or (
        kind in {"Stack", "Track"} and node.get("source_range") is not None
    )


def _reportable(schema, node, pointer, scopes):
    if not schema:
        return False
    if schema not in otio_import._KNOWN:
        return True
    kind = schema.partition(".")[0]
    if kind in otio_import._ELEMENTS:
        return True
    if schema == "Stack.1":
        return (
            pointer != scopes["rootStack"]
            or _parent_treatment(node, kind)
            or node.get("enabled") is False
        )
    return kind in _COMPOSITIONS and pointer != scopes["timeline"]


def _direct(kind, pointer, scopes):
    if kind == "Track":
        return pointer in scopes["tracks"]
    return kind in {"Clip", "Gap"} and pointer in scopes["children"]


def _unsupported(schema, node, pointer, scopes, placed):
    if schema not in otio_import._KNOWN:
        return (
            "OTIO_SCHEMA_UNSUPPORTED",
            "The original content schema requires separate reconstruction",
        )
    if schema == "Marker.1":
        return None
    kind = schema.partition(".")[0]
    if kind in _TREATMENTS:
        return (
            "OTIO_TREATMENT_UNSUPPORTED",
            "This treatment is outside supported original-source reconstruction",
        )
    if kind in _COMPOSITIONS:
        return (
            "OTIO_TREATMENT_UNSUPPORTED",
            "Nested composition or root-stack treatment is unsupported",
        )
    if not _direct(kind, pointer, scopes):
        return (
            "OTIO_TREATMENT_UNSUPPORTED",
            "This content is not a direct supported track occurrence",
        )
    if _parent_treatment(node, kind):
        return (
            "OTIO_TREATMENT_UNSUPPORTED",
            "Parent trims and effects require separate reconstruction",
        )
    if not placed and (kind == "Gap" or node.get("enabled") is False):
        return (
            "OTIO_TREATMENT_UNSUPPORTED",
            "Gaps and disabled content require the placed-layout capability",
        )
    return None


def _finding(pointer, code, message):
    return {
        "code": code,
        "scope": pointer,
        "message": message,
        "blocking": True,
        "evidenceOrigin": "capability-check",
        "remediation": "Remove the unsupported treatment from a new standalone export or reconstruct this scoped element with a qualified capability.",
    }


def _element(export_hash, pointer, schema, node, disposition):
    name = node.get("name", "")
    identity = hashlib.sha256(
        (export_hash + "\x00" + pointer).encode("utf-8")
    ).hexdigest()
    row = {
        "pointer": pointer,
        "schema": schema,
        "name": name[:240] if isinstance(name, str) else "",
        "elementId": "element-" + identity,
        "disposition": disposition,
        "evidenceOrigin": "export",
    }
    if schema.partition(".")[0] in {"Track", "Clip"}:
        enabled = node.get("enabled", True)
        if type(enabled) is bool:
            row["enabled"] = enabled
    reference = otio_import.reference_metadata(pointer, node)
    if reference:
        row["referenceMetadata"] = reference
    return row


def _append_detail(report, row, finding):
    row_size = len(canonical_json_bytes(row)) + 1
    finding_size = len(canonical_json_bytes(finding)) + 1 if finding else 0
    row_room = len(report["elements"]) < MAX_ELEMENTS
    finding_room = finding is None or len(report["findings"]) < MAX_FINDINGS
    if row_room and finding_room and row_size + finding_size <= report["remaining"]:
        report["elements"].append(row)
        report["remaining"] -= row_size + finding_size
        if finding is not None:
            report["findings"].append(finding)
    elif finding is not None and finding_room and finding_size <= report["remaining"]:
        report["findings"].append(finding)
        report["remaining"] -= finding_size


def _record(report, export_hash, pointer, schema, node, scopes, context):
    unsupported = _unsupported(schema, node, pointer, scopes, context["placed"])
    if unsupported is not None:
        disposition = "unsupported"
    elif schema == "Marker.1":
        disposition = "reference-metadata"
    else:
        disposition = "reconstructed" if context["ready"] else "unresolved"
    report["counts"][disposition] += 1
    finding = None
    if unsupported is not None:
        report["unsupported"] += 1
        code, message = unsupported
        finding = _finding(pointer, code, message)
    row = _element(export_hash, pointer, schema, node, disposition)
    _append_detail(report, row, finding)


def _finish(report):
    total = sum(report["counts"].values())
    omitted_elements = total - len(report["elements"])
    omitted_findings = report["unsupported"] - len(report["findings"])
    truncated = bool(omitted_elements or omitted_findings)
    if truncated:
        report["findings"].append(
            {
                "code": "OTIO_INPUT_LIMIT",
                "scope": "",
                "message": f"Bounded detail omitted {omitted_elements} elements and {omitted_findings} unsupported findings; complete disposition counts remain available",
                "blocking": True,
                "evidenceOrigin": "capability-check",
                "remediation": "Inspect a smaller standalone timeline selection before activation.",
            }
        )
    findings_total = report["unsupported"] + int(truncated)
    accounting = {
        "total": total,
        "reported": len(report["elements"]),
        "truncated": truncated,
        "byDisposition": {key: report["counts"][key] for key in _DISPOSITIONS},
        "findingsTotal": findings_total,
        "findingsReported": len(report["findings"]),
        "findingsTruncated": findings_total > len(report["findings"]),
    }
    payload = {
        "elements": report["elements"],
        "accounting": accounting,
        "findings": report["findings"],
    }
    if len(canonical_json_bytes(payload)) > MAX_DETAIL_BYTES:
        raise otio_import.ImportError(
            "OTIO_INPUT_LIMIT", "Element detail budget cannot hold its bounded summary"
        )
    return report["elements"], accounting, report["findings"]


def account_elements(data: bytes, pointer: str, *, checks: dict, declarations: dict):
    """Account for the selected raw content without granting editorial approval."""
    _, raw, _ = otio_import.parse_export_bytes(data)
    _, selected = otio_import._select(raw, pointer)
    scopes = _direct_scopes(selected, pointer)
    context = {
        "placed": declarations.get("layoutMode") == "placed",
        "ready": all(
            checks.get(key) == "passed" for key in ("semanticValidation", "mediaReady")
        ),
    }
    report = {
        "elements": [],
        "findings": [],
        "counts": Counter(),
        "unsupported": 0,
        "remaining": MAX_DETAIL_BYTES - _RESERVED_BYTES,
    }
    export_hash = hashlib.sha256(data).hexdigest()
    for location, node in _content_nodes(selected, pointer):
        schema = otio_import._schema(node, location)
        if _reportable(schema, node, location, scopes):
            _record(report, export_hash, location, schema, node, scopes, context)
    return _finish(report)
