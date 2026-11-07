"""Bounded, dependency-free OTIO inventory; never media or render authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, DecimalException
from fractions import Fraction
from pathlib import Path

from .contracts import content_hash

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 128
MAX_OBJECTS = 100_000
MAX_REPORT_ITEMS = 2048
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_POINTER_LENGTH = 2048
NORMALIZER_VERSION = "2.0.0"
_KNOWN = {
    "Timeline.1",
    "Stack.1",
    "Track.1",
    "Clip.1",
    "Clip.2",
    "Gap.1",
    "RationalTime.1",
    "TimeRange.1",
    "ExternalReference.1",
    "MissingReference.1",
    "GeneratorReference.1",
    "Marker.1",
    "SerializableCollection.1",
    "Transition.1",
    "Effect.1",
    "TimeEffect.1",
    "LinearTimeWarp.1",
    "FreezeFrame.1",
}
_ELEMENTS = {
    "Track",
    "Clip",
    "Gap",
    "Marker",
    "Transition",
    "Effect",
    "TimeEffect",
    "LinearTimeWarp",
    "FreezeFrame",
}


class ImportError(ValueError):
    def __init__(self, code, message, *, scope=""):
        super().__init__(message)
        self.code = code
        self.scope = scope

    def to_dict(self):
        return {
            "code": self.code,
            "message": str(self),
            "scope": self.scope,
            "blocking": True,
            "remediation": "Supply a supported standalone OTIO export and resolve the reported input or selection.",
        }


def _limit(message):
    raise ImportError("OTIO_INPUT_LIMIT", message)


def packet_identity(
    export_hash,
    timeline_pointer,
    provider,
    video_id,
    options,
    *,
    normalizer_version=NORMALIZER_VERSION,
):
    """Identify an interpretation, distinct from the original export's byte hash."""
    return content_hash(
        {
            "exportSha256": export_hash,
            "timelinePointer": timeline_pointer,
            "provider": provider,
            "videoId": video_id,
            "options": options,
            "normalizerVersion": normalizer_version,
        }
    )


def exact_rate(value, declarations, scope=""):
    """A decimal rate is evidence, never an implicit NTSC-rate declaration."""
    rate = _clock_fraction(value, scope)
    interpretations = declarations.get("rateInterpretations", {})
    if not isinstance(interpretations, dict):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Rate interpretations must be an object", scope=scope
        )
    chosen = interpretations.get(str(value))
    if chosen is not None:
        rate = _clock_fraction(chosen, scope)
        if abs(rate - _clock_fraction(value, scope)) > Fraction(1, 1000):
            raise ImportError(
                "OTIO_RATE_UNVERIFIED",
                "Declared rate contradicts the export",
                scope=scope,
            )
    elif rate.denominator != 1:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Declare the exact rational meaning of this decimal rate",
            scope=scope,
        )
    if rate <= 0:
        raise ImportError("OTIO_INPUT_INVALID", "Rate must be positive", scope=scope)
    return rate


def _clock_fraction(value, scope):
    text = str(value)
    if len(text) > 128:
        raise ImportError(
            "OTIO_INPUT_LIMIT",
            "Clock declaration exceeds its numeric bound",
            scope=scope,
        )
    try:
        parts = [Decimal(part) for part in text.split("/")]
        if any(not part.is_finite() or abs(part.adjusted()) > 18 for part in parts):
            raise ValueError("Clock magnitude is out of range")
        return Fraction(text)
    except (ValueError, DecimalException, ZeroDivisionError) as exc:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Invalid or out-of-range clock declaration",
            scope=scope,
        ) from exc


def _seconds(value, declarations, scope):
    if not isinstance(value, dict) or set(value) != {"value", "rate"}:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Time evidence requires exact value/rate fields",
            scope=scope,
        )
    return _clock_fraction(value["value"], scope) / exact_rate(
        value["rate"], declarations, scope
    )


def _eligible_node(node, allowed):
    scope = node["pointer"]
    if node.get("schema") not in allowed:
        raise ImportError(
            "OTIO_SCHEMA_UNSUPPORTED",
            "This content is outside the contiguous reconstruction subset",
            scope=scope,
        )
    if (
        node.get("enabled") is False
        or node.get("parentTrim")
        or node.get("effectsCount")
    ):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Disabled content, parent trims and effects require separate support",
            scope=scope,
        )
    if node.get("nativeRangeError"):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Native timing could not be computed", scope=scope
        )


def _active_external(raw, scope):
    active = raw.get("media_reference")
    if raw.get("OTIO_SCHEMA") == "Clip.2":
        active = (raw.get("media_references") or {}).get(
            raw.get("active_media_reference_key")
        )
    if not active or active.get("OTIO_SCHEMA") != "ExternalReference.1":
        raise ImportError(
            "OTIO_SCHEMA_UNSUPPORTED",
            "An active external original-media reference is required",
            scope=scope,
        )
    return active


def _contiguous_clip(raw, facts, elapsed, declarations):
    scope = facts["pointer"]
    _eligible_node(facts, {"Clip.1", "Clip.2"})
    active = _active_external(raw, scope)
    source_range = _range(raw.get("source_range")) or _range(
        active.get("available_range")
    )
    available = _range(active.get("available_range"))
    if not available:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Media start origin is not exported; declare it before reconstruction",
            scope=scope,
        )
    start = _seconds(source_range["start"], declarations, scope) - _seconds(
        available["start"], declarations, scope
    )
    duration = _seconds(source_range["duration"], declarations, scope)
    program = facts["programRange"]
    native_start = _seconds(program["start"], declarations, scope)
    native_duration = _seconds(program["duration"], declarations, scope)
    if abs(native_start - elapsed) > Fraction(1, 10**8) or abs(
        native_duration - duration
    ) > Fraction(1, 10**8):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Native placement does not match an unretimed contiguous sequence",
            scope=scope,
        )
    if start < 0 or duration <= 0:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Source range is outside its original-media origin",
            scope=scope,
        )
    return {
        "pointer": scope,
        "referencePointer": facts["referencePointer"],
        "targetUrl": active.get("target_url", ""),
        "start": start,
        "duration": duration,
        "availableDuration": _seconds(available["duration"], declarations, scope),
    }


def _native_selection(native, pointer):
    facts = next(
        (item for item in native.get("timelines", []) if item["pointer"] == pointer),
        None,
    )
    if facts is None:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Native reader did not return the selected timeline",
            scope=pointer,
        )
    _eligible_node(facts, {"Timeline.1"})
    return facts


def _single_picture_track(selected, facts, pointer):
    stack = selected["tracks"]
    if (
        stack.get("source_range")
        or stack.get("effects")
        or stack.get("enabled") is False
    ):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Timeline stack treatment is unsupported",
            scope=pointer,
        )
    tracks = [
        (raw_track, fact)
        for raw_track, fact in zip(stack["children"], facts["tracks"], strict=True)
        if raw_track.get("children")
    ]
    if len(tracks) != 1 or tracks[0][1]["kind"] != "Video":
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "M1 requires exactly one contributing picture track with linked source audio",
            scope=pointer,
        )
    raw_track, track = tracks[0]
    _eligible_node(track, {"Track.1"})
    return raw_track, track


def _declared_media_origins(selected, pointer, declarations):
    origins = declarations.get("mediaOrigins", {})
    scope = "/declarations/mediaOrigins"
    if not isinstance(origins, dict):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Media origins must be a scoped object", scope=scope
        )
    references = {
        location: node
        for location, node, content, active in _walk(selected, pointer)
        if content
        and active is True
        and node.get("OTIO_SCHEMA") == "ExternalReference.1"
    }
    for reference, value in origins.items():
        if reference not in references:
            raise ImportError(
                "OTIO_INPUT_INVALID",
                "Media-origin declaration does not select an active reference",
                scope=scope + reference,
            )
        declared = _seconds(value, declarations, scope + reference)
        available = _range(references[reference].get("available_range"))
        if available and declared != _seconds(
            available["start"], declarations, reference
        ):
            raise ImportError(
                "OTIO_RATE_UNVERIFIED",
                "Declared media origin contradicts exported origin",
                scope=scope + reference,
            )


def normalize_contiguous(data, native, pointer, declarations):
    """Qualify the entire selection using raw exact clocks and native placements."""
    _, raw, _ = parse_export_bytes(data)
    _, selected = _select(raw, pointer)
    _declared_media_origins(selected, pointer, declarations)
    _, counts, _, _, findings = _inventory(selected, pointer)
    if findings or any(
        counts[kind]
        for kind in (
            "Transition",
            "Gap",
            "Effect",
            "TimeEffect",
            "LinearTimeWarp",
            "FreezeFrame",
        )
    ):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "The whole export must fit the supported contiguous subset",
            scope=pointer,
        )
    facts = _native_selection(native, pointer)
    raw_track, track = _single_picture_track(selected, facts, pointer)
    clips, elapsed = [], Fraction(0)
    for raw_clip, fact in zip(raw_track["children"], track["children"], strict=True):
        clip = _contiguous_clip(raw_clip, fact, elapsed, declarations)
        clips.append(clip)
        elapsed += clip["duration"]
    return {
        "clips": clips,
        "duration": elapsed,
        "globalStart": _time(selected.get("global_start_time")),
    }


def _placed_eligible(node, allowed):
    scope = node["pointer"]
    if node.get("schema") not in allowed:
        raise ImportError(
            "OTIO_SCHEMA_UNSUPPORTED", "Unsupported placed content", scope=scope
        )
    if node.get("parentTrim") or node.get("effectsCount"):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Parent trims and effects require separate support",
            scope=scope,
        )
    if node.get("nativeRangeError"):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Native timing could not be computed", scope=scope
        )


def _placed_clip(raw, fact, elapsed, declarations):
    scope = fact["pointer"]
    _placed_eligible(fact, {"Clip.1", "Clip.2"})
    active = _active_external(raw, scope)
    available = _range(active.get("available_range"))
    source = _range(raw.get("source_range")) or available
    origins = declarations.get("mediaOrigins", {})
    if not isinstance(origins, dict):
        raise ImportError("OTIO_INPUT_INVALID", "Media origins must be a scoped object")
    origin = available["start"] if available else origins.get(fact["referencePointer"])
    if not origin or not source:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Media origin/source range requires exported evidence or a scoped declaration",
            scope=scope,
        )
    start = _seconds(source["start"], declarations, scope) - _seconds(
        origin, declarations, scope
    )
    duration = _seconds(source["duration"], declarations, scope)
    if start < 0 or duration <= 0:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Source range is outside its original-media origin",
            scope=scope,
        )
    _placed_native_range(fact, elapsed, duration, declarations)
    return {
        "pointer": scope,
        "referencePointer": fact["referencePointer"],
        "targetUrl": active.get("target_url", ""),
        "start": start,
        "duration": duration,
        "availableDuration": _seconds(available["duration"], declarations, scope)
        if available
        else None,
        "programStart": elapsed,
        "enabled": raw.get("enabled", True),
    }


def _placed_native_range(fact, start, duration, declarations):
    scope = fact["pointer"]
    program = fact.get("programRange")
    if not program or any(
        abs(actual - expected) > Fraction(1, 10**8)
        for actual, expected in (
            (_seconds(program["start"], declarations, scope), start),
            (_seconds(program["duration"], declarations, scope), duration),
        )
    ):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Native placement contradicts the exact unretimed sequence",
            scope=scope,
        )


def _placed_track(raw, fact, declarations, order):
    _placed_eligible(fact, {"Track.1"})
    if fact.get("kind") not in {"Video", "Audio"}:
        raise ImportError(
            "OTIO_SCHEMA_UNSUPPORTED", "Unknown track kind", scope=fact["pointer"]
        )
    kind = fact["kind"].lower()
    track = {
        "trackId": "track-" + content_hash(fact["pointer"])[:24],
        "kind": kind,
        "order": order,
        "enabled": raw.get("enabled", True),
        "muted": False,
        "evidenceOrigin": "export",
        "name": str(raw.get("name", ""))[:240],
    }
    clips, gaps, elapsed = [], [], Fraction(0)
    for child, child_fact in zip(raw["children"], fact["children"], strict=True):
        _placed_eligible(child_fact, {"Clip.1", "Clip.2", "Gap.1"})
        if child_fact["schema"] == "Gap.1":
            duration = _seconds(
                (_range(child.get("source_range")) or {}).get("duration"),
                declarations,
                child_fact["pointer"],
            )
            _placed_native_range(child_fact, elapsed, duration, declarations)
            gaps.append(
                {
                    "pointer": child_fact["pointer"],
                    "trackId": track["trackId"],
                    "programStart": elapsed,
                    "duration": duration,
                }
            )
        else:
            clip = _placed_clip(child, child_fact, elapsed, declarations)
            clip.update(trackId=track["trackId"], mediaKind=kind)
            clips.append(clip)
            duration = clip["duration"]
        elapsed += duration
    return track, clips, gaps, elapsed


def normalize_placed(data, native, pointer, declarations):
    """Preserve every direct track occurrence with exact half-open program clocks."""
    _, raw, _ = parse_export_bytes(data)
    _, selected = _select(raw, pointer)
    _declared_media_origins(selected, pointer, declarations)
    _, counts, _, _, findings = _inventory(selected, pointer)
    if findings or any(
        counts[key]
        for key in (
            "Transition",
            "Effect",
            "TimeEffect",
            "LinearTimeWarp",
            "FreezeFrame",
        )
    ):
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Unsupported content requires separate reconstruction",
            scope=pointer,
        )
    facts = _native_selection(native, pointer)
    _placed_eligible(facts, {"Timeline.1"})
    stack = selected["tracks"]
    tracks, clips, gaps, ends = [], [], [], []
    for order, (track, fact) in enumerate(
        zip(stack["children"], facts["tracks"], strict=True)
    ):
        normalized, children, spaces, end = _placed_track(
            track, fact, declarations, order
        )
        tracks.append(normalized)
        clips.extend(children)
        gaps.extend(spaces)
        ends.append(end)
    if not clips:
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "No original-media placements are exported",
            scope=pointer,
        )
    return {
        "tracks": tracks,
        "clips": clips,
        "gaps": gaps,
        "duration": max(ends),
        "globalStart": _time(selected.get("global_start_time")),
    }


def _check_depth(text):
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                _limit(f"OTIO nesting exceeds {MAX_DEPTH}")
        elif char in "]}":
            depth -= 1


def read_export(path):
    """Read bounded exact bytes and raw JSON without following any references."""
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise ImportError("OTIO_INPUT_INVALID", f"Cannot read OTIO: {exc}") from exc
    return parse_export_bytes(data)


def parse_export_bytes(data):
    """Apply the same structural resource guards to an isolated reader's stdin."""
    try:
        if len(data) > MAX_INPUT_BYTES:
            _limit(f"OTIO input exceeds {MAX_INPUT_BYTES} bytes")
        text = data.decode("utf-8-sig")
        _check_depth(text)
        objects = 0

        def pairs(items):
            nonlocal objects
            objects += 1
            if objects > MAX_OBJECTS:
                _limit(f"OTIO input exceeds {MAX_OBJECTS} objects")
            result = dict(items)
            if len(result) != len(items):
                raise ValueError("duplicate JSON keys")
            return result

        def constant(value):
            raise ValueError(f"nonfinite JSON number: {value}")

        value = json.loads(
            text, parse_float=Decimal, parse_constant=constant, object_pairs_hook=pairs
        )
        if not isinstance(value, dict):
            raise ValueError("OTIO root must be an object")
        return data, value, objects
    except ImportError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError, DecimalException) as exc:
        raise ImportError("OTIO_INPUT_INVALID", f"Cannot read OTIO: {exc}") from exc


def _pointer(parent, key):
    key = str(key)
    if len(key) + len(parent) + 1 > MAX_POINTER_LENGTH:
        _limit(f"OTIO pointer exceeds {MAX_POINTER_LENGTH} characters")
    pointer = parent + "/" + key.replace("~", "~0").replace("/", "~1")
    if len(pointer) > MAX_POINTER_LENGTH:
        _limit(f"OTIO pointer exceeds {MAX_POINTER_LENGTH} characters")
    return pointer


def _children(value, pointer, content, active):
    for key, child in value.items():
        location = _pointer(pointer, key)
        child_content = content and key != "metadata"
        if key == "media_references" and isinstance(child, dict):
            selected = value.get("active_media_reference_key")
            for name, reference in child.items():
                chosen = name == selected if selected is not None else None
                yield reference, _pointer(location, name), child_content, chosen
        else:
            chosen = True if key == "media_reference" else active
            yield child, location, child_content, chosen


def _walk(value, pointer="", content=True, active=None):
    if isinstance(value, dict):
        yield pointer, value, content, active
        for arguments in _children(value, pointer, content, active):
            yield from _walk(*arguments)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, _pointer(pointer, index), content, active)


def _select(value, timeline):
    if value.get("OTIO_SCHEMA") == "Timeline.1":
        candidates = [("", value)]
    elif value.get("OTIO_SCHEMA") == "SerializableCollection.1":
        candidates = [
            (p, v)
            for p, v, content, _ in _walk(value)
            if content and v.get("OTIO_SCHEMA") == "Timeline.1"
        ]
    else:
        raise ImportError(
            "OTIO_INPUT_INVALID", "Root must be Timeline.1 or SerializableCollection.1"
        )
    if timeline is not None:
        candidates = [(p, v) for p, v in candidates if p == timeline]
    if len(candidates) != 1:
        raise ImportError(
            "OTIO_TIMELINE_SELECTION",
            "Explicitly select one timeline using its JSON pointer",
        )
    return candidates[0]


def _time(value):
    if not isinstance(value, dict):
        return None
    return {key: str(value[key]) for key in ("value", "rate") if key in value}


def _range(value):
    if not isinstance(value, dict):
        return None
    return {
        "start": _time(value.get("start_time")),
        "duration": _time(value.get("duration")),
    }


def _reference_notes(node):
    metadata = node.get("metadata")
    scopes = (node, metadata if isinstance(metadata, dict) else {})
    return [
        value
        for scope in scopes
        for key in ("note", "notes", "comment")
        if isinstance(value := scope.get(key), str)
    ]


def _reference_note_fields(notes):
    selected = notes[:4]
    return {
        "notes": [note[:4096] for note in selected],
        "notesTruncated": len(notes) > 4 or any(len(note) > 4096 for note in selected),
    }


def _reference_clock_scalar(value):
    if type(value) not in (int, float, Decimal, str):
        return False
    text = str(value)
    return (
        len(text) <= 128
        and re.fullmatch(
            r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text
        )
        is not None
    )


def _reference_marked_range(value):
    if not isinstance(value, dict):
        return None
    for key in ("start_time", "duration"):
        time = value.get(key)
        if not isinstance(time, dict) or not all(
            _reference_clock_scalar(time.get(field)) for field in ("value", "rate")
        ):
            return None
    return _range(value)


def reference_metadata(pointer, node):
    """Retain only bounded, inert note strings and unconverted marker evidence."""
    notes = _reference_notes(node)
    schema = node.get("OTIO_SCHEMA", "")
    marker = isinstance(schema, str) and schema.partition(".")[0] == "Marker"
    if not marker and not notes:
        return {}
    owner = (
        pointer.rpartition("/markers/")[0]
        if marker and "/markers/" in pointer
        else pointer
    )
    result = {"ownerPointer": owner}
    if marker:
        marked = _reference_marked_range(node.get("marked_range"))
        if marked is not None:
            result["markedRange"] = marked
    if notes:
        result.update(_reference_note_fields(notes))
    return result


def _append(items, item):
    if len(items) < MAX_REPORT_ITEMS:
        items.append(item)


def _schema(item, pointer):
    schema = item.get("OTIO_SCHEMA", "")
    if not isinstance(schema, str) or len(schema) > 128:
        raise ImportError(
            "OTIO_INPUT_INVALID", "Invalid OTIO_SCHEMA label", scope=pointer[:2048]
        )
    return schema


def _check_time(schema, item, pointer):
    if schema != "RationalTime.1":
        return
    rate = item.get("rate")
    if type(rate) not in (int, Decimal) or rate <= 0:
        raise ImportError(
            "OTIO_INPUT_INVALID", "Time rate must be positive", scope=pointer[:2048]
        )


def _record_content(pointer, item, schema, active, elements, references, findings):
    kind = schema.split(".")[0]
    if kind in _ELEMENTS:
        row = {
            "pointer": pointer[:2048],
            "schema": schema,
            "name": str(item.get("name", ""))[:240],
            "sourceRange": _range(item.get("source_range")),
            "disposition": "unresolved",
        }
        reference = reference_metadata(pointer, item)
        if reference:
            row["referenceMetadata"] = reference
        _append(elements, row)
    if kind.endswith("Reference"):
        _append(
            references,
            {
                "pointer": pointer[:2048],
                "schema": schema,
                "targetUrl": str(item.get("target_url", ""))[:1024],
                "active": active,
                "availableRange": _range(item.get("available_range")),
            },
        )
    if schema not in _KNOWN:
        _append(
            findings,
            {
                "code": "OTIO_SCHEMA_UNSUPPORTED",
                "scope": pointer[:2048],
                "schema": schema,
                "blocking": True,
                "evidenceOrigin": "export",
                "remediation": "Qualify this content schema before reconstruction.",
            },
        )


def _inventory(value, prefix):
    schemas, counts = Counter(), Counter()
    elements, references, findings = [], [], []
    for pointer, item, content, active in _walk(value, prefix):
        schema = _schema(item, pointer)
        if schema:
            schemas[schema] += 1
        if not content or not schema:
            continue
        _check_time(schema, item, pointer)
        counts[schema.split(".")[0]] += 1
        counts["findings"] += int(schema not in _KNOWN)
        counts["scalarTruncations"] += _scalar_truncations(schema, item)
        _record_content(pointer, item, schema, active, elements, references, findings)
    return schemas, counts, elements, references, findings


def _scalar_truncations(schema, item):
    kind = schema.split(".")[0]
    name = kind in _ELEMENTS and len(str(item.get("name", ""))) > 240
    url = kind.endswith("Reference") and len(str(item.get("target_url", ""))) > 1024
    notes = _reference_notes(item) if kind in _ELEMENTS else []
    note_truncations = sum(len(note) > 4096 for note in notes[:4]) + max(
        0, len(notes) - 4
    )
    return int(name) + int(url) + note_truncations


def _bound_report(result):
    while (
        len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_REPORT_BYTES
    ):
        before = sum(len(result[key]) for key in ("elements", "references", "findings"))
        if not before:
            _limit(f"OTIO fixed report fields exceed {MAX_REPORT_BYTES} bytes")
        result["truncated"] = True
        for key in ("elements", "references", "findings"):
            result[key] = result[key][: len(result[key]) // 2]
    return result


def inspect_export(path, *, timeline=None):
    data, value, objects = read_export(path)
    pointer, selected = _select(value, timeline)
    schemas, counts, elements, references, findings = _inventory(selected, pointer)
    counts["scalarTruncations"] += int(len(str(selected.get("name", ""))) > 240)
    total_elements = sum(counts[kind] for kind in _ELEMENTS)
    total_refs = sum(
        count for kind, count in counts.items() if kind.endswith("Reference")
    )
    result = {
        "schemaVersion": "1.0.0",
        "operation": "inspect",
        "status": "inspected",
        "capabilityLevel": "diagnostic",
        "source": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "sizeBytes": len(data),
            "timelinePointer": pointer,
        },
        "name": str(selected.get("name", ""))[:240],
        "schemas": dict(sorted(schemas.items())[:MAX_REPORT_ITEMS]),
        "summary": {
            "clips": counts["Clip"],
            "tracks": counts["Track"],
            "gaps": counts["Gap"],
            "markers": counts["Marker"],
            "effects": sum(
                counts[k]
                for k in ("Effect", "TimeEffect", "LinearTimeWarp", "FreezeFrame")
            ),
            "transitions": counts["Transition"],
            "references": total_refs,
            "objects": objects,
            "scalarTruncations": counts["scalarTruncations"],
            "globalStartTime": _time(selected.get("global_start_time")),
            "timingValidation": "not-checked",
        },
        "elements": elements,
        "references": references,
        "findings": findings,
        "readiness": {
            "inspectionComplete": True,
            "semanticValidation": "not-checked",
            "mediaReady": "not-checked",
            "syncReady": "not-checked",
            "reconstructionReady": "not-checked",
            "activationAllowed": False,
            "reviewState": "not-started",
        },
        "nextAction": "Review this structural inventory. Semantic reconstruction and original-media validation have not run.",
        "truncated": total_elements > len(elements)
        or total_refs > len(references)
        or counts["findings"] > len(findings)
        or counts["scalarTruncations"] > 0
        or len(schemas) > MAX_REPORT_ITEMS,
    }
    return _bound_report(result)
