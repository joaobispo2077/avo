"""Qualified native OTIO core reading in a bounded, plugin-free worker."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from importlib import metadata

from avo.timeline import otio_import
from avo.timeline.otio_import import ImportError as TimelineImportError

NATIVE_VERSION = "0.18.1"
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_ERROR_CODES = {
    "OTIO_INPUT_INVALID",
    "OTIO_INPUT_LIMIT",
    "OTIO_RUNTIME_UNAVAILABLE",
}


def worker_environment():
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"):
        env.pop(key, None)
    env.update(
        OTIO_PLUGIN_MANIFEST_PATH="",
        OTIO_DISABLE_ENTRYPOINTS_PLUGINS="1",
        PYTHONNOUSERSITE="1",
    )
    return env


def _require_runtime():
    try:
        version = metadata.version("opentimelineio")
    except (metadata.PackageNotFoundError, OSError, ValueError) as exc:
        raise TimelineImportError(
            "OTIO_RUNTIME_UNAVAILABLE",
            "Install the resolve-import extra in a checkout, or reinstall an "
            "AVO engine built with native Resolve import support.",
        ) from exc
    if version != NATIVE_VERSION:
        raise TimelineImportError(
            "OTIO_RUNTIME_UNAVAILABLE",
            f"The resolve-import extra requires OpenTimelineIO {NATIVE_VERSION}.",
        )


def _decode_response(completed):
    if not isinstance(completed.stdout, bytes):
        raise TimelineImportError("OTIO_INPUT_INVALID", "Invalid native reader output")
    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        raise TimelineImportError(
            "OTIO_INPUT_LIMIT", "Native reader output exceeds limit"
        )
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError) as exc:
        raise TimelineImportError(
            "OTIO_INPUT_INVALID", "Native reader returned invalid JSON"
        ) from exc
    if not isinstance(result, dict):
        raise TimelineImportError(
            "OTIO_INPUT_INVALID", "Invalid native reader envelope"
        )
    _raise_worker_error(result)
    if completed.returncode:
        raise TimelineImportError(
            "OTIO_RUNTIME_UNAVAILABLE",
            "Native reader could not complete in this runtime",
        )
    if set(result) != {"nativeVersion", "document", "timelines"}:
        raise TimelineImportError(
            "OTIO_INPUT_INVALID", "Invalid native reader envelope"
        )
    if result["nativeVersion"] != NATIVE_VERSION or not isinstance(
        result["document"], dict
    ):
        raise TimelineImportError(
            "OTIO_INPUT_INVALID", "Invalid native reader document"
        )
    _validate_timeline_facts(result["timelines"])
    return result


def _validate_timeline_facts(timelines):
    if not isinstance(timelines, list):
        raise TimelineImportError("OTIO_INPUT_INVALID", "Invalid native timeline facts")
    for timeline in timelines:
        if not isinstance(timeline, dict) or not isinstance(
            timeline.get("pointer"), str
        ):
            raise TimelineImportError(
                "OTIO_INPUT_INVALID", "Invalid native timeline facts"
            )
        if not isinstance(timeline.get("tracks"), list):
            raise TimelineImportError(
                "OTIO_INPUT_INVALID", "Invalid native track facts"
            )


def _raise_worker_error(result):
    error = result.get("error")
    if error is None:
        return
    if not isinstance(error, dict) or error.get("code") not in _ERROR_CODES:
        raise TimelineImportError("OTIO_INPUT_INVALID", "Invalid native reader error")
    raise TimelineImportError(
        error["code"],
        str(error.get("message", "Native reader failed"))[:1024],
        scope=str(error.get("scope", ""))[:2048],
    )


def read_otio(data: bytes) -> dict:
    _require_runtime()
    if not isinstance(data, bytes):
        raise TimelineImportError("OTIO_INPUT_INVALID", "Native reader requires bytes")
    otio_import.parse_export_bytes(data)
    command = (
        [sys.executable, "otio-worker", "--worker"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-I", "-m", "avo.adapters.media.otio_reader", "--worker"]
    )
    try:
        completed = subprocess.run(
            command,
            input=data,
            capture_output=True,
            timeout=60,
            shell=False,
            env=worker_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimelineImportError(
            "OTIO_INPUT_LIMIT", "Native reader exceeded its 60 second limit"
        ) from exc
    except OSError as exc:
        raise TimelineImportError(
            "OTIO_RUNTIME_UNAVAILABLE", "Native reader worker could not start"
        ) from exc
    return _decode_response(completed)


def _native_time(value):
    if value is None:
        return None
    if (
        not math.isfinite(value.value)
        or not math.isfinite(value.rate)
        or value.rate <= 0
    ):
        raise ValueError("Native time has a nonfinite value or invalid rate")
    return {"value": repr(value.value), "rate": repr(value.rate)}


def _native_range(value):
    if value is None:
        return None
    return {
        "start": _native_time(value.start_time),
        "duration": _native_time(value.duration),
    }


def _capture_range(facts, field, callback, converter=_native_range):
    try:
        facts[field] = converter(callback())
    except Exception as exc:
        facts[field] = None
        facts["nativeRangeError"].append(
            {"scope": facts["pointer"], "field": field, "message": str(exc)[:512]}
        )


def _native_schema(item):
    return f"{item.schema_name()}.{item.schema_version()}"


def _raw_child(raw, index):
    children = raw.get("children") if isinstance(raw, dict) else None
    if not isinstance(children, list) or index >= len(children):
        return {}
    return children[index] if isinstance(children[index], dict) else {}


def _node_facts(item, raw, pointer, program):
    native_schema = _native_schema(item)
    facts = {
        "pointer": pointer,
        "schema": raw.get("OTIO_SCHEMA", native_schema),
        "nativeSchema": native_schema,
        "name": str(getattr(item, "name", "")),
        "enabled": getattr(item, "enabled", None),
        "effectsCount": len(getattr(item, "effects", ())),
        "nestedComposition": item.schema_name() in {"Stack", "Track"},
        "parentTrim": item.schema_name() in {"Stack", "Track"}
        and getattr(item, "source_range", None) is not None,
        "nativeRangeError": [],
    }
    _capture_range(facts, "sourceRange", lambda: getattr(item, "source_range", None))
    _capture_range(facts, "trimmedSourceRange", lambda: item.trimmed_range())
    _capture_range(facts, "parentRange", lambda: item.range_in_parent())
    _capture_range(
        facts,
        "programRange",
        lambda: item.transformed_time_range(item.trimmed_range(), program),
    )
    return facts


def _file_relative_range(trimmed, available):
    return type(trimmed)(trimmed.start_time - available.start_time, trimmed.duration)


def _clip_reference(facts, item, raw):
    facts.update(
        activeReferenceKey=None,
        referencePointer=None,
        targetUrl=None,
        referenceSchema=None,
        availableRange=None,
        fileRelativeSourceRange=None,
    )
    try:
        key = item.active_media_reference_key
        reference = item.media_reference
        facts["activeReferenceKey"] = key
        if raw.get("OTIO_SCHEMA") == "Clip.1":
            facts["referencePointer"] = otio_import._pointer(
                facts["pointer"], "media_reference"
            )
        elif raw.get("OTIO_SCHEMA") == "Clip.2":
            base = otio_import._pointer(facts["pointer"], "media_references")
            facts["referencePointer"] = otio_import._pointer(base, key)
        facts["referenceSchema"] = _native_schema(reference)
        facts["targetUrl"] = getattr(reference, "target_url", None)
        available = reference.available_range
    except Exception as exc:
        facts["nativeRangeError"].append(
            {
                "scope": facts["pointer"],
                "field": "activeReference",
                "message": str(exc)[:512],
            }
        )
        return
    _capture_range(facts, "availableRange", lambda: available)
    if available is not None:
        _capture_range(
            facts,
            "fileRelativeSourceRange",
            lambda: _file_relative_range(item.trimmed_range(), available),
        )


def _track_facts(track, raw, pointer, program):
    facts = _node_facts(track, raw, pointer, program)
    facts["kind"] = getattr(track, "kind", None)
    facts["children"] = []
    if track.schema_name() != "Track":
        return facts
    for index, child in enumerate(track):
        child_raw = _raw_child(raw, index)
        location = otio_import._pointer(
            otio_import._pointer(pointer, "children"), index
        )
        item = _node_facts(child, child_raw, location, program)
        if child.schema_name() == "Clip":
            _clip_reference(item, child, child_raw)
        facts["children"].append(item)
    return facts


def _timeline_facts(timeline, raw, pointer):
    program = timeline.tracks
    facts = {
        "pointer": pointer,
        "schema": raw.get("OTIO_SCHEMA", _native_schema(timeline)),
        "nativeSchema": _native_schema(timeline),
        "name": str(timeline.name),
        "enabled": program.enabled,
        "effectsCount": len(program.effects),
        "parentTrim": program.source_range is not None,
        "nativeRangeError": [],
        "tracks": [],
    }
    _capture_range(
        facts, "globalStart", lambda: timeline.global_start_time, _native_time
    )
    _capture_range(facts, "duration", timeline.duration, _native_time)
    raw_program = raw.get("tracks") if isinstance(raw.get("tracks"), dict) else {}
    track_base = otio_import._pointer(
        otio_import._pointer(pointer, "tracks"), "children"
    )
    for index, track in enumerate(program):
        location = otio_import._pointer(track_base, index)
        facts["tracks"].append(
            _track_facts(track, _raw_child(raw_program, index), location, program)
        )
    return facts


def _collect_timelines(item, raw, pointer=""):
    if item.schema_name() == "Timeline":
        yield _timeline_facts(item, raw, pointer)
    elif item.schema_name() == "SerializableCollection":
        for index, child in enumerate(item):
            location = otio_import._pointer(
                otio_import._pointer(pointer, "children"), index
            )
            yield from _collect_timelines(child, _raw_child(raw, index), location)


def _native_document(data, raw):
    try:
        import opentimelineio
    except Exception as exc:
        raise TimelineImportError(
            "OTIO_RUNTIME_UNAVAILABLE", "The resolve-import native core is unavailable"
        ) from exc
    try:
        document = opentimelineio.core.deserialize_json_from_string(
            data.decode("utf-8-sig")
        )
        serialized = opentimelineio.core.serialize_json_to_string(document, None, -1)
        return json.loads(serialized), list(_collect_timelines(document, raw))
    except TimelineImportError:
        raise
    except Exception as exc:
        raise TimelineImportError(
            "OTIO_INPUT_INVALID", f"Native OTIO interpretation failed: {str(exc)[:512]}"
        ) from exc


def _worker_response():
    _require_runtime()
    data = sys.stdin.buffer.read(otio_import.MAX_INPUT_BYTES + 1)
    _, raw, _ = otio_import.parse_export_bytes(data)
    document, timelines = _native_document(data, raw)
    response = {
        "nativeVersion": NATIVE_VERSION,
        "document": document,
        "timelines": timelines,
    }
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise TimelineImportError(
            "OTIO_INPUT_LIMIT", "Native reader output exceeds limit"
        )
    return encoded


def _worker_main():
    clean_environment = worker_environment()
    os.environ.clear()
    os.environ.update(clean_environment)
    try:
        encoded = _worker_response()
    except Exception as exc:
        error = (
            exc.to_dict()
            if isinstance(exc, TimelineImportError)
            else {"code": "OTIO_INPUT_INVALID", "message": str(exc)[:1024]}
        )
        error["message"] = str(error["message"])[:1024]
        sys.stdout.buffer.write(json.dumps({"error": error}).encode("utf-8"))
        return 3
    sys.stdout.buffer.write(encoded)
    return 0


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments != ["--worker"]:
        raise SystemExit("This module is an internal OTIO reader worker.")
    return _worker_main()


if __name__ == "__main__":
    raise SystemExit(main())
