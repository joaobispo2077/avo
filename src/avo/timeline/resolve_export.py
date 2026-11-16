"""Export-driven effect reconstruction; unknown data stays canonical and inert."""

import json
import math
from collections import Counter
from decimal import Decimal
from fractions import Fraction

from .contracts import canonical_json_bytes
from .otio_import import MAX_REPORT_ITEMS, ImportError, _pointer, _walk
from .resolve_effects import inactive_effect

EXPORT_MODE = "export-driven"


def _plain_number(value):
    if not isinstance(value, Decimal):
        raise TypeError("Unsupported effect metadata value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Effect metadata number exceeds supported bounds")
    return result


def plain_payload(value):
    payload = json.loads(json.dumps(value, default=_plain_number, allow_nan=False))
    if len(canonical_json_bytes(payload)) > 64 * 1024:
        raise ImportError(
            "OTIO_INPUT_LIMIT", "An effect/reference payload exceeds 64 KiB"
        )
    return payload


def _effect_collection(node, location):
    effects = node.get("effects", [])
    if not isinstance(effects, list) or any(not isinstance(e, dict) for e in effects):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Invalid exported effect collection", scope=location
        )
    return effects


def _resolve_metadata(effect):
    metadata = effect.get("metadata", {})
    if not isinstance(metadata, dict):
        return {}
    value = metadata.get("Resolve_OTIO", {})
    return value if isinstance(value, dict) else {}


def _effect_record(effect, location, index):
    metadata = _resolve_metadata(effect)
    return {
        "pointer": _pointer(_pointer(location, "effects"), index),
        "ownerPointer": location,
        "name": str(
            metadata.get("Effect Name") or effect.get("effect_name") or "Effect"
        )[:240],
        "state": "inactive" if inactive_effect(effect) else "unresolved",
        "payload": plain_payload(effect),
        "evidenceOrigin": "export",
    }


def _ordinary_effects(effects):
    return [(i, e) for i, e in enumerate(effects) if e.get("OTIO_SCHEMA") == "Effect.1"]


def collect_export_effects(selected, pointer):
    records, owners = [], set()
    schemas = {"Timeline.1", "Stack.1", "Track.1", "Clip.1", "Clip.2"}
    for location, node, content, _ in _walk(selected, pointer):
        if not content or node.get("OTIO_SCHEMA") not in schemas:
            continue
        effects = _effect_collection(node, location)
        ordinary = _ordinary_effects(effects)
        if effects and len(ordinary) == len(effects):
            owners.add(location)
        records.extend(_effect_record(e, location, i) for i, e in ordinary)
        if len(records) > MAX_REPORT_ITEMS:
            raise ImportError("OTIO_INPUT_LIMIT", "Too many exported effect records")
    if len(canonical_json_bytes(records)) > 8 * 1024 * 1024:
        raise ImportError(
            "OTIO_INPUT_LIMIT", "Exported effect payloads exceed their total byte limit"
        )
    return records, owners


def _parameter_items(metadata):
    items = metadata.get("Parameters", [])
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        return []
    return items


def _parameters(record):
    metadata = _resolve_metadata(record["payload"])
    if not isinstance(metadata, dict) or metadata.get("Enabled") is not True:
        return None
    items = _parameter_items(metadata)
    result = {}
    for item in items:
        key = item.get("Parameter ID")
        if not isinstance(key, str) or key in result or item.get("Key Frames"):
            return None
        value = item.get("Parameter Value")
        if type(value) not in (int, float) or not math.isfinite(value):
            return None
        result[key] = Fraction(str(value))
    return result or None


def _transform(parameters, output, stream):
    keys = {
        "transformationZoomX",
        "transformationZoomY",
        "transformationPan",
        "transformationTilt",
    }
    if set(parameters) != keys:
        return None
    cw, ch = output["width"], output["height"]
    sw, sh = stream["width"], stream["height"]
    fit = min(Fraction(cw, sw), Fraction(ch, sh))
    width = round(sw * fit * parameters["transformationZoomX"])
    height = round(sh * fit * parameters["transformationZoomY"])
    x = round(Fraction(cw - width, 2) + parameters["transformationPan"] * cw)
    y = round(Fraction(ch - height, 2) - parameters["transformationTilt"] * ch)
    if not (
        1 <= width <= 8192
        and 1 <= height <= 8192
        and abs(x) <= 65536
        and abs(y) <= 65536
    ):
        return None
    return {
        "pictureTransform": {
            "canvasWidth": cw,
            "canvasHeight": ch,
            "width": width,
            "height": height,
            "x": x,
            "y": y,
        }
    }


def _faders(parameters):
    if set(parameters) - {"videoFaderIn", "videoFaderOut"}:
        return None
    if any(
        value.denominator != 1 or not 0 <= value <= 1_000_000
        for value in parameters.values()
    ):
        return None
    return {
        "pictureFade": {
            "inFrames": int(parameters.get("videoFaderIn", 0)),
            "outFrames": int(parameters.get("videoFaderOut", 0)),
        }
    }


def _picture_operation(name, parameters, output, stream):
    if name == "Transform" and stream is not None:
        return _transform(parameters, output, stream)
    if name == "Video Faders":
        return _faders(parameters)
    return None


def picture_treatments(records, owner, output, stream, *, duration_frames):
    """Translate only complete supported static parameter sets; retain the rest."""
    operations, resolved = {}, []
    for record in records:
        if record["ownerPointer"] != owner or record["state"] != "unresolved":
            continue
        parameters = _parameters(record)
        if parameters is None:
            continue
        operation = _picture_operation(record["name"], parameters, output, stream)
        if not _bounded_operation(operation, duration_frames):
            continue
        if operation and not set(operation).intersection(operations):
            operations.update(operation)
            resolved.append(record)
    for record in resolved:
        record["state"] = "reconstructed"
    return operations


def _bounded_operation(operation, duration_frames):
    if not operation:
        return False
    if "pictureFade" not in operation:
        return True
    fade = operation["pictureFade"]
    return fade["inFrames"] + fade["outFrames"] <= duration_frames


def _active_placements(layout):
    tracks = {
        t["trackId"]
        for t in layout.get("tracks", [])
        if t["enabled"] and not t["muted"]
    }
    return [
        p
        for p in layout.get("placements", [])
        if p["enabled"] and p["trackId"] in tracks
    ]


def _owns_active(owner, owners):
    return not owner or any(p == owner or p.startswith(owner + "/") for p in owners)


def _unverified_clocks(snapshot, placements):
    if snapshot.get("layout", {}).get("importMode") != EXPORT_MODE:
        return []
    sources = {s["sourceId"]: s for s in snapshot.get("sources", [])}
    videos = [p for p in placements if p["mediaKind"] == "video"]
    return [
        {"name": "Original video clock", "pointer": p["elementId"]}
        for p in videos
        if sources[p["sourceId"]]
        .get("streamMetadata", {})
        .get("videoClock", {})
        .get("status")
        != "verified"
    ]


def unresolved_treatments(snapshot):
    layout = snapshot.get("layout", {})
    placements = _active_placements(layout)
    owners = {p["elementId"] for p in placements}
    unresolved = [
        r
        for r in layout.get("resolveEffects", [])
        if r["state"] == "unresolved" and _owns_active(r["ownerPointer"], owners)
    ]
    unresolved.extend(
        {"name": "Generated reference", "pointer": p["elementId"]}
        for p in placements
        if p["mediaKind"] == "generator"
    )
    unresolved.extend(_unverified_clocks(snapshot, placements))
    return unresolved


def import_approximation(snapshot, *, authorization):
    """Freeze explicit effect omissions for an unpromotable imported preview."""
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError("An imported approximation requires explicit authorization")
    unresolved = unresolved_treatments(snapshot)
    effects = {
        r["pointer"] for r in snapshot.get("layout", {}).get("resolveEffects", [])
    }
    if any(r["pointer"] not in effects for r in unresolved):
        raise ValueError(
            "Approximation cannot waive unverified clocks or generated sources"
        )
    return {
        "policy": "supported-treatments-only-v1",
        "authorization": authorization,
        "omittedEffects": sorted(
            ({"pointer": r["pointer"], "name": r["name"]} for r in unresolved),
            key=lambda r: r["pointer"],
        ),
    }


def require_renderable_import(snapshot, *, approximation=None, preview_only=False):
    if approximation is not None:
        if not isinstance(approximation, dict):
            raise ValueError("Imported approximation must be an explicit policy object")
        if preview_only is not True:
            raise ValueError("Imported approximations must remain preview-only")
        expected = import_approximation(
            snapshot, authorization=approximation.get("authorization")
        )
        if approximation != expected:
            raise ValueError(
                "Imported approximation omits stale or unaccounted treatments"
            )
        return
    unresolved = unresolved_treatments(snapshot)
    if unresolved:
        names = ", ".join(sorted({r["name"] for r in unresolved}))
        raise ValueError(
            f"Imported treatments are preserved but unsupported for rendering: {names}. The structural draft remains editable."
        )


def import_warnings(snapshot):
    counts = Counter(row["name"] for row in unresolved_treatments(snapshot))
    return [
        {
            "code": "OTIO_TREATMENT_UNSUPPORTED",
            "scope": "/layout/resolveEffects",
            "message": f"Preserved {count} occurrence(s) of {name}; rendering support is pending.",
            "blocking": False,
            "evidenceOrigin": "capability-check",
            "remediation": "Continue editing the imported draft. Final proof rendering remains gated until this retained feature is supported; opening Resolve is not required for import.",
        }
        for name, count in sorted(counts.items())
    ]
