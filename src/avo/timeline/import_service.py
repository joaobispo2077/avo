"""Staged, provider-bound timeline handoffs; canonical selection is separate."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname
from uuid import uuid4

from avo.paths import providers_dir, repo_root

from .contracts import (
    canonical_json_bytes,
    content_hash,
    file_fingerprint,
    fingerprint_stage,
    validate_document,
)
from .otio_import import (
    NORMALIZER_VERSION,
    ImportError,
    inspect_export,
    normalize_contiguous,
    normalize_placed,
    packet_identity,
    parse_export_bytes,
    read_export,
)
from .store import (
    StoreError,
    atomic_write_json,
    now_iso,
    timeline_writer,
    write_immutable_json,
)
from .workspace import ARTIFACTS, TimelineWorkspace, map_wsl_mnt_path

_SCHEMA = "avo.timeline-import.schema.json"
_HASH = re.compile(r"^[a-f0-9]{64}$")
_MAX_STORED_BYTES = 64 * 1024 * 1024


def _finite_number(text):
    value = float(text)
    if not math.isfinite(value):
        raise ImportError("OTIO_INPUT_INVALID", "Stored numeric value is out of range")
    return value


def _bounded_bytes(path):
    if Path(path).stat().st_size > _MAX_STORED_BYTES:
        raise ImportError("OTIO_INPUT_LIMIT", "Stored document exceeds 64 MiB")
    with Path(path).open("rb") as stream:
        data = stream.read(_MAX_STORED_BYTES + 1)
    if len(data) > _MAX_STORED_BYTES:
        raise ImportError("OTIO_INPUT_LIMIT", "Stored document exceeds 64 MiB")
    return data


def _decode_document(data):
    parse_export_bytes(data)
    return json.loads(data.decode("utf-8-sig"), parse_float=_finite_number)


def _document(path):
    return _decode_document(_bounded_bytes(path))


def _contained(base, relative):
    base = Path(base).resolve()
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base) or candidate == base:
        raise ImportError("OTIO_TARGET_CONFLICT", "Import path escapes its packet")
    return candidate


def _immutable_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ImportError(
                    "OTIO_SOURCE_CHANGED", "Immutable export bytes differ"
                )
    except OSError as exc:
        raise ImportError(
            "OTIO_TARGET_CONFLICT", "Cannot publish immutable export on this filesystem"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _absolute_location(value):
    if not isinstance(value, (str, Path)):
        raise ImportError("OTIO_INPUT_INVALID", "Media location must be a path")
    _require_local_path(value)
    path = map_wsl_mnt_path(value).expanduser()
    if not path.is_absolute():
        raise ImportError(
            "OTIO_INPUT_INVALID", "Media locations must be absolute paths"
        )
    return str(path.resolve())


def _option_objects(mappings, declarations):
    if mappings is not None and not isinstance(mappings, dict):
        raise ImportError("OTIO_INPUT_INVALID", "Mappings must be a JSON object")
    if declarations is not None and not isinstance(declarations, dict):
        raise ImportError("OTIO_INPUT_INVALID", "Declarations must be a JSON object")


def _options(media_roots, mappings, declarations):
    _option_objects(mappings, declarations)
    normalized = {}
    for reference, value in (mappings or {}).items():
        item = {"path": value} if isinstance(value, (str, Path)) else deepcopy(value)
        if not isinstance(item, dict) or "path" not in item:
            raise ImportError(
                "OTIO_INPUT_INVALID", "Mapping requires a path", scope=str(reference)
            )
        item["path"] = _absolute_location(item["path"])
        item["status"] = "unresolved"
        normalized[str(reference)] = item
    result = {
        "mediaRoots": sorted({_absolute_location(root) for root in media_roots}),
        "mappings": normalized,
        "declarations": deepcopy(declarations or {}),
    }
    validate_document(result, _SCHEMA + "#/$defs/options")
    return result


def _merge_repair_mappings(previous, mappings):
    if mappings is not None and not isinstance(mappings, dict):
        raise ImportError("OTIO_INPUT_INVALID", "Mappings must be a JSON object")
    merged = deepcopy(previous)
    for pointer, mapping in (mappings or {}).items():
        if not isinstance(mapping, dict):
            raise ImportError(
                "OTIO_INPUT_INVALID", "Each mapping must be an object", scope=pointer
            )
        merged[pointer] = {**merged.get(pointer, {}), **mapping}
    return merged


def _repair_options(predecessor, source, roots, mappings, declarations):
    if predecessor is None:
        return _options(roots or (), mappings, declarations)
    if source != predecessor["source"]:
        raise ImportError(
            "OTIO_TARGET_CONFLICT",
            "A repair predecessor must have the same exact export and timeline selection",
        )
    old = predecessor["options"]
    options = _options(
        old["mediaRoots"] if roots is None else roots,
        _merge_repair_mappings(old["mappings"], mappings),
        old["declarations"] if declarations is None else declarations,
    )
    options["supersedesImportId"] = predecessor["importId"]
    validate_document(options, _SCHEMA + "#/$defs/options")
    return options


def _clock_port(probe, override):
    return (
        override
        if override is not None
        else getattr(getattr(probe, "__self__", None), "verify_video_clock", None)
    )


def _mapping_defaults(source):
    defaults = {
        key: deepcopy(value)
        for key, value in source["streamMetadata"].items()
        if key in {"videoStreamIndex", "audioSelection"}
    }
    path = source["locator"]
    defaults["path"] = path
    defaults["fingerprint"] = {
        "path": path,
        "sha256": source["fingerprint"]["sha256"],
        "sizeBytes": source["fingerprint"]["sizeBytes"],
    }
    return defaults


def _local_reference(url):
    _require_local_path(url)
    if Path(url).is_absolute():
        return map_wsl_mnt_path(url).expanduser()
    parsed = urlsplit(url)
    if parsed.scheme not in {"", "file"} or parsed.netloc not in {"", "localhost"}:
        raise ImportError(
            "OTIO_SOURCE_PROHIBITED", "Only declared local original files can be read"
        )
    decoded = url2pathname(parsed.path) if parsed.scheme else url
    _require_local_path(decoded)
    return map_wsl_mnt_path(decoded).expanduser()


def _require_local_path(value):
    text = str(value)
    if len(text) > 32767:
        raise ImportError(
            "OTIO_INPUT_LIMIT", "Original-media path exceeds the local path limit"
        )
    if text.replace("\\", "/").startswith("//"):
        raise ImportError(
            "OTIO_SOURCE_PROHIBITED",
            "Network shares are outside the local-original import capability",
        )


def _time_value(seconds, source_id, fps):
    ticks = seconds * fps
    if ticks.denominator != 1:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED", "Source boundary is not an exact output frame"
        )
    return {
        "ticks": ticks.numerator,
        "timebase": {"num": fps.denominator, "den": fps.numerator},
        "domain": "raw-source",
        "sourceId": source_id,
    }


def _exact_time(seconds, domain, source_id=None):
    result = {
        "ticks": seconds.numerator,
        "timebase": {"num": 1, "den": seconds.denominator},
        "domain": domain,
    }
    if source_id is not None:
        result["sourceId"] = source_id
    return result


def _program_time(seconds, fps):
    ticks = seconds * fps
    if ticks.denominator != 1:
        return _exact_time(seconds, "cmap-output")
    return {
        "ticks": ticks.numerator,
        "timebase": {"num": fps.denominator, "den": fps.numerator},
        "domain": "cmap-output",
    }


def _finding(error):
    return {
        "code": error.code,
        "scope": error.scope,
        "message": str(error),
        "blocking": True,
        "evidenceOrigin": "editor-declaration"
        if error.scope.startswith("/declarations")
        else "capability-check",
        "remediation": "Resolve the scoped source, timing or unsupported treatment, then prepare and validate again.",
    }


def _audio_state(mapping, kind, scope):
    state = {key: mapping[key] for key in ("gainDb", "muted") if key in mapping}
    if state and kind != "audio":
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Gain and mute declarations require an independent audio placement",
            scope=scope,
        )
    if state:
        state["evidenceOrigin"] = "editor-declaration"
    return state


def _placed_raw_bounds(clip, kind, fps, source_id):
    start = Fraction(0) if kind == "still" else clip["start"]
    end = Fraction(1, 1) / fps if kind == "still" else clip["start"] + clip["duration"]
    return {
        "in": _exact_time(start, "raw-source", source_id),
        "out": _exact_time(end, "raw-source", source_id),
    }


def _verified_mappings(references, snapshot):
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    segments = {
        item["segmentId"]: item["sourceId"] for item in snapshot.get("segments", [])
    }
    placements = {
        item["elementId"]: item["sourceId"]
        for item in snapshot.get("layout", {}).get("placements", [])
    }
    result, used = {}, 0
    for reference in references:
        pointer = reference["pointer"]
        parent = pointer.rpartition("/")[0]
        owner = parent.removesuffix("/media_references")
        source_id = placements.get(owner) or segments.get(
            "otio-" + content_hash(owner)[:24]
        )
        if source_id is None:
            continue
        source = sources[source_id]
        fingerprint = source["fingerprint"]
        mapping = {
            "status": "verified",
            "candidates": [],
            "selected": {
                "path": source["locator"],
                "sourceId": source_id,
                "fingerprint": {
                    "sha256": fingerprint["sha256"],
                    "sizeBytes": fingerprint["sizeBytes"],
                },
                "matchBasis": "canonical-source-ref",
            },
        }
        used += len(canonical_json_bytes({pointer: mapping}))
        if used > 8 * 1024 * 1024:
            return result, [
                _finding(
                    ImportError(
                        "OTIO_INPUT_LIMIT",
                        "Verified source details exceed the report budget; retained proposal sources remain available",
                        scope="mediaMappings",
                    )
                )
            ]
        result[pointer] = mapping
    return result, []


def _checked_readiness(checks, sync, *, attempted, state):
    if not attempted:
        return {
            **checks,
            "syncReady": "not-checked",
            "reconstructionReady": "not-checked",
        }
    return {
        **checks,
        "syncReady": "passed" if sync else "not-ready",
        "reconstructionReady": "passed"
        if state == "ready-to-activate"
        else "not-ready",
    }


def _output_settings(declarations):
    if declarations.get("sourceOnly") is not True:
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Declare and verify whether this is a source-only edit; export metadata cannot establish omitted treatments",
        )
    output = deepcopy(declarations.get("output") or {})
    required = {"width", "height", "frameRate", "audioSampleRate", "channelLayout"}
    if not isinstance(output, dict) or set(output) != required:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Declare exact output dimensions, frame rate, sample rate and channel layout",
        )
    _declared_rate(output["frameRate"])
    if (
        any(
            type(output[key]) is not int or output[key] <= 0
            for key in ("width", "height", "audioSampleRate")
        )
        or output["channelLayout"] != "stereo"
    ):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "M1 requires declared positive dimensions/sample rate and stereo output",
        )
    return output


def _declared_output(declarations, source):
    allowed = {
        "sourceOnly",
        "output",
        "layoutMode",
        "rateInterpretations",
        "mediaOrigins",
        "omittedTreatments",
        "treatments",
        "exportSha256",
    }
    unknown = set(declarations) - allowed
    if unknown:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Unsupported declaration fields cannot grant import authority",
            scope="/declarations",
        )
    if declarations.get("layoutMode", "contiguous") not in {"contiguous", "placed"}:
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Unsupported declared layout mode",
            scope="/declarations/layoutMode",
        )
    _declared_treatments(declarations)
    if declarations.get("exportSha256", source["sha256"]) != source["sha256"]:
        raise ImportError(
            "OTIO_SOURCE_CHANGED",
            "Declarations are bound to a different export",
            scope="/declarations/exportSha256",
        )
    try:
        return _output_settings(declarations)
    except ImportError as exc:
        raise ImportError(exc.code, str(exc), scope="/declarations/output") from exc


def _declared_treatments(declarations):
    for key in ("omittedTreatments", "treatments"):
        if not isinstance(declarations.get(key, []), list):
            raise ImportError(
                "OTIO_INPUT_INVALID",
                "Treatment declarations must be a list",
                scope="/declarations/" + key,
            )
        if declarations.get(key):
            raise ImportError(
                "OTIO_TREATMENT_UNSUPPORTED",
                "Declared audiovisual treatment is not reconstructed by this source-only capability; retain it or provide a separately revised export",
                scope="/declarations/" + key,
            )


def _require_source_only_proposal(proposal):
    if proposal["provisionalFinishing"]:
        raise ImportError(
            "OTIO_TREATMENT_UNSUPPORTED",
            "Imported finishing is not reconstructed by the source-only capability; retain it as reference until supported authoring against the approved cut",
            scope="/provisionalFinishing",
        )


def _declared_rate(rate):
    if (
        not isinstance(rate, dict)
        or set(rate) != {"num", "den"}
        or any(type(rate[key]) is not int or rate[key] <= 0 for key in rate)
    ):
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Output frame rate requires positive integer numerator and denominator",
        )


def _selected_stream(streams, index, kind, scope):
    if type(index) is not int or index < 0:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Stream index must be an explicit nonnegative integer",
            scope=scope,
        )
    found = [stream for stream in streams.get(kind, []) if stream["index"] == index]
    if len(found) != 1:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Selected media stream is missing or ambiguous",
            scope=scope,
        )
    return found[0]


def _stream_selection(mapping, described, output, scope):
    video = _selected_stream(
        described["streams"], mapping.get("videoStreamIndex"), "video", scope
    )
    _square_picture(video, scope)
    audio = deepcopy(mapping.get("audioSelection") or {})
    selected = _selected_stream(
        described["streams"], audio.get("streamIndex"), "audio", scope
    )
    _audio_selection(audio, selected, scope)
    fps = Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
    if not _matching_cfr(video, fps):
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Source video rate does not match the declared M1 output rate",
            scope=scope,
        )
    audio["sourceSampleRate"] = selected["sampleRate"]
    return {"videoStreamIndex": video["index"], "audioSelection": audio}


def _square_picture(video, scope):
    value = video.get("sampleAspectRatio")
    if value in (None, "", "N/A", "0:1"):
        return
    try:
        square = Fraction(str(value).replace(":", "/")) == 1
    except (ValueError, ZeroDivisionError):
        square = False
    if not square:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "This capability requires square picture pixels",
            scope=scope,
        )


def _audio_selection(audio, selected, scope):
    allowed = {
        "streamIndex",
        "channels",
        "sourceLayout",
        "outputLayout",
        "sourceSampleRate",
    }
    if set(audio) - allowed:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Unsupported audio-selection properties require an explicit supported routing",
            scope=scope,
        )
    _audio_channels(audio, selected, scope)
    if "sourceSampleRate" in audio and (
        type(audio["sourceSampleRate"]) is not int
        or audio["sourceSampleRate"] != selected.get("sampleRate")
    ):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Declared native sample rate contradicts the selected original",
            scope=scope,
        )
    if type(selected.get("sampleRate")) is not int or selected["sampleRate"] <= 0:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Selected audio sample rate is unknown",
            scope=scope,
        )
    _supported_audio_layout(audio, selected, scope)


def _supported_audio_layout(audio, selected, scope):
    if audio.get("outputLayout") not in {"stereo", "dual-mono"} or audio.get(
        "sourceLayout"
    ) not in {"mono", "stereo"}:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Declare supported mono/stereo source layout and stereo/dual-mono routing",
            scope=scope,
        )
    if selected["channels"] != {"mono": 1, "stereo": 2}[audio["sourceLayout"]]:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Source channel count contradicts its declared supported layout",
            scope=scope,
        )
    if (
        selected.get("channelLayout")
        and selected["channelLayout"] != audio["sourceLayout"]
    ):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Declared channel layout contradicts the probe",
            scope=scope,
        )


def _matching_cfr(video, fps):
    try:
        return (
            Fraction(video["frameRate"]) == Fraction(video["averageFrameRate"]) == fps
        )
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return False


def _audio_channels(audio, selected, scope):
    channels = audio.get("channels", [])
    if (
        not isinstance(channels, list)
        or not channels
        or any(
            type(ch) is not int or not 0 <= ch < selected["channels"] for ch in channels
        )
    ):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Declare valid source audio channels",
            scope=scope,
        )
    required_count = {"stereo": 2, "dual-mono": 1}.get(audio.get("outputLayout"))
    if len(channels) != required_count:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Stereo requires two selected channels; dual-mono requires one",
            scope=scope,
        )


def _probed_seconds(stream, mode, scope):
    ticks_key, seconds_key = {
        "start": ("startTicks", "startTimeSeconds"),
        "duration": ("durationTicks", "durationSeconds"),
    }[mode]
    try:
        if type(stream.get(ticks_key)) is int and stream.get("timeBase"):
            return stream[ticks_key] * Fraction(stream["timeBase"])
        if stream.get(seconds_key) is not None:
            return Fraction(str(stream[seconds_key]))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED", "Selected stream clock is invalid", scope=scope
        ) from exc
    raise ImportError(
        "OTIO_RATE_UNVERIFIED",
        "Selected stream origin or extent is unverified",
        scope=scope,
    )


def _linked_stream_bounds(info, metadata, clip):
    scope = clip["referencePointer"]
    video = _selected_stream(
        info["streams"], metadata["videoStreamIndex"], "video", scope
    )
    audio = _selected_stream(
        info["streams"], metadata["audioSelection"]["streamIndex"], "audio", scope
    )
    if _probed_seconds(video, "start", scope) != _probed_seconds(audio, "start", scope):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Linked source streams have different origins; M1 cannot infer an audio offset",
            scope=scope,
        )
    end = clip["start"] + clip["duration"]
    if any(
        end > _probed_seconds(stream, "duration", scope) for stream in (video, audio)
    ):
        raise ImportError(
            "OTIO_SOURCE_CHANGED",
            "Imported interval exceeds a selected media stream",
            scope=scope,
        )


def _import_next_action(state):
    return {
        "prepared": "Validate the exact staged packet before selecting an edit",
        "awaiting-sync": "Establish current approved Sync/N/A for these exact originals, then validate again",
        "ready-to-activate": "Review the active edit diff; explicitly select its validation hash and exact expected head",
        "active-draft": "Build the canonical cut proof, then obtain current transcript, Watch, listening and creator review",
        "superseded": "Keep the current canonical selection; inspect it before another explicit activation or return",
        "recovery-required": "Restore reported source/evidence changes, then retry the exact recorded activation or return",
    }.get(
        state,
        "Resolve the scoped findings and validate a repaired packet before selecting an edit",
    )


class TimelineImportService:
    def __init__(
        self,
        project_path,
        *,
        provider=None,
        provider_root=None,
        reader=None,
        probe=None,
        still_probe=None,
        clock_probe=None,
    ):
        self.workspace = TimelineWorkspace.from_project(Path(project_path))
        self.provider = str(self.workspace.project.get("provider") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.provider):
            raise ImportError("OTIO_TARGET_CONFLICT", "A declared provider is required")
        if provider is not None and provider != self.provider:
            raise ImportError(
                "OTIO_TARGET_CONFLICT", "Provider conflicts with target project"
            )
        self._check_target()
        directory = (
            Path(provider_root)
            if provider_root is not None
            else providers_dir() / self.provider
        )
        self.provider_manifest_path = directory / "avo.provider.json"
        try:
            self.provider_manifest = _document(directory / "avo.provider.json")
            validate_document(
                self.provider_manifest, "avo.provider.schema.json", root=providers_dir()
            )
        except (OSError, ValueError) as exc:
            raise ImportError(
                "OTIO_TARGET_CONFLICT", "Provider manifest is missing or invalid"
            ) from exc
        if self.provider_manifest.get("name") != self.provider:
            raise ImportError(
                "OTIO_TARGET_CONFLICT", "Provider manifest identity differs"
            )
        self.root = (self.workspace.timeline_dir / "imports").resolve()
        edit = (self.workspace.raw_dir / "edit").resolve()
        if not self.root.is_relative_to(edit) or not edit.is_relative_to(
            self.workspace.raw_dir
        ):
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "Import storage must remain under the project's edit directory",
            )
        self.reader, self.probe = reader, probe
        self.still_probe = still_probe
        self.clock_probe = _clock_port(probe, clock_probe)
        self.context_lock = self._read_context_lock()

    def _read_context_lock(self):
        project_data = _bounded_bytes(self.workspace.project_path)
        provider_data = _bounded_bytes(self.provider_manifest_path)
        if (
            _decode_document(project_data) != self.workspace.project
            or _decode_document(provider_data) != self.provider_manifest
        ):
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "Project or provider configuration changed; reload and validate the current target",
            )
        info = self.workspace.raw_dir.stat()
        timeline = self.workspace.timeline_dir.resolve()
        imports = (self.workspace.timeline_dir / "imports").resolve()
        if not timeline.is_relative_to(self.workspace.raw_dir) or imports != self.root:
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "Resolved timeline/import destination changed or escaped the declared project",
            )
        return {
            "projectSha256": hashlib.sha256(project_data).hexdigest(),
            "providerSha256": hashlib.sha256(provider_data).hexdigest(),
            "rawRootIdentity": {"device": info.st_dev, "fileId": info.st_ino},
            "timelineRoot": str(timeline),
            "importsRoot": str(imports),
        }

    def _check_context(self):
        if self._read_context_lock() != self.context_lock:
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "Project/provider configuration or target folder identity changed",
            )

    def _check_target(self):
        project = self.workspace.project
        if not project.get("rawDir"):
            raise ImportError("OTIO_TARGET_CONFLICT", "Explicit rawDir is required")
        declared = map_wsl_mnt_path(project["rawDir"]).expanduser()
        if not declared.is_absolute():
            declared = self.workspace.project_path.parent / declared
        if declared.resolve() != self.workspace.raw_dir.resolve():
            raise ImportError(
                "OTIO_TARGET_CONFLICT", "Declared rawDir cannot use a fallback folder"
            )
        if self.workspace.raw_dir.resolve().is_relative_to(repo_root().resolve()):
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "Footage projects must remain outside the orchestrator repository",
            )
        for kind in ARTIFACTS:
            if not self.workspace.artifact_path(kind).is_file():
                continue
            index = self.workspace.store(kind).load_index()
            if (index["provider"], index["videoId"]) != (
                self.provider,
                self.workspace.video_id,
            ):
                raise ImportError(
                    "OTIO_TARGET_CONFLICT",
                    "Existing canonical identity conflicts with the project",
                )

    def head_hash(self):
        if not self.workspace.artifact_path("cmap").is_file():
            return "empty"
        store = self.workspace.store("cmap")
        index = store.load_index()
        if not index["headRevisionId"]:
            return "empty"
        return store.revision(index["headRevisionId"])["contentHash"]

    def packet_path(self, import_id, relative="index.json"):
        if not isinstance(import_id, str) or not _HASH.fullmatch(import_id):
            raise ImportError("OTIO_INPUT_INVALID", "Invalid import identity")
        packet = _contained(self.root, import_id)
        return _contained(packet, relative)

    def _ref(self, import_id, path):
        fingerprint = file_fingerprint(path)
        return {
            "path": path.relative_to(self.root / import_id).as_posix(),
            "sha256": fingerprint["sha256"],
            "sizeBytes": fingerprint["sizeBytes"],
        }

    def read_ref(self, import_id, reference):
        path = self.packet_path(import_id, reference["path"])
        if reference["sizeBytes"] > _MAX_STORED_BYTES:
            raise ImportError("OTIO_INPUT_LIMIT", "Evidence declaration exceeds 64 MiB")
        data = _bounded_bytes(path)
        actual = {"sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if any(actual[key] != reference[key] for key in ("sha256", "sizeBytes")):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Import evidence bytes changed",
                scope=reference["path"],
            )
        return _decode_document(data) if path.suffix == ".json" else data

    def load(self, import_id):
        try:
            value = _document(self.packet_path(import_id))
            validate_document(value, _SCHEMA)
            self._check_packet_identity(value, import_id)
            for reference in value["refs"].values():
                self.read_ref(import_id, reference)
            return value
        except ImportError:
            raise
        except (OSError, ValueError, KeyError) as exc:
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Cannot verify staged import"
            ) from exc

    def _check_packet_identity(self, value, import_id):
        if (value["provider"], value["videoId"]) != (
            self.provider,
            self.workspace.video_id,
        ):
            raise ImportError(
                "OTIO_TARGET_CONFLICT", "Staged import belongs to a different target"
            )
        if not {"export", "snapshot"} <= value["refs"].keys():
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Staged import is missing its original evidence"
            )
        export = value["refs"]["export"]
        if any(export[key] != value["source"][key] for key in ("sha256", "sizeBytes")):
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Export identity differs from staged source"
            )
        expected = packet_identity(
            value["source"]["sha256"],
            value["source"]["timelinePointer"],
            self.provider,
            self.workspace.video_id,
            value["options"],
            normalizer_version=value["normalizerVersion"],
        )
        if value["importId"] != import_id or expected != import_id:
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Import identity or options changed"
            )
        if value.get("supersedesImportId") != value["options"].get(
            "supersedesImportId"
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Import predecessor differs from its hash-bound options",
            )

    def _result(self, operation, session, **fields):
        result = {
            "schemaVersion": "1.0.0",
            "operation": operation,
            "capabilityLevel": "placed-experimental"
            if session["options"]["declarations"].get("layoutMode") == "placed"
            else "contiguous-experimental",
            "readiness": {
                "inspectionComplete": True,
                "semanticValidation": "not-checked",
                "mediaReady": "not-checked",
                "syncReady": "not-checked",
                "reconstructionReady": "not-checked",
                "activationAllowed": False,
                "reviewState": "not-started",
            },
            "status": session["state"],
            "importId": session["importId"],
            "source": session["source"],
            "target": {
                "provider": self.provider,
                "videoId": self.workspace.video_id,
                "projectPath": str(self.workspace.project_path),
            },
            "session": session,
            **fields,
        }

        result.setdefault("nextAction", _import_next_action(result["status"]))
        return result

    def _predecessor(self, import_id, timeline):
        if import_id is None:
            return None, timeline
        previous = self.load(import_id)
        self._lock_repair_sources(previous)
        return previous, previous["source"][
            "timelinePointer"
        ] if timeline is None else timeline

    def _lock_repair_sources(self, previous):
        reference = previous["refs"].get("proposal")
        if reference is None:
            return
        proposal = self.read_ref(previous["importId"], reference)
        snapshot = proposal.get("snapshot", {})
        if not snapshot.get("sources"):
            return
        inventory = self.read_ref(previous["importId"], previous["refs"]["snapshot"])
        references = [
            row
            for row in inventory["inventory"]["references"]
            if row.get("active") is True
        ]
        verified, findings = _verified_mappings(references, snapshot)
        if findings:
            raise ImportError(
                "OTIO_INPUT_LIMIT",
                "Predecessor source locks exceed the repair detail budget",
            )
        sources = {source["sourceId"]: source for source in snapshot["sources"]}
        for pointer, row in verified.items():
            selected = row["selected"]
            source = sources[selected["sourceId"]]
            previous["options"]["mappings"][pointer] = {
                **_mapping_defaults(source),
                **previous["options"]["mappings"].get(pointer, {}),
            }

    def prepare(
        self,
        input_path,
        *,
        timeline=None,
        media_roots=None,
        mappings=None,
        declarations=None,
        supersedes_import_id=None,
        actor,
        reason,
    ):
        self._check_context()
        if not str(actor).strip() or not str(reason).strip():
            raise ImportError(
                "OTIO_INPUT_INVALID", "Import actor and reason are required"
            )
        predecessor, timeline = self._predecessor(supersedes_import_id, timeline)
        inventory = inspect_export(input_path, timeline=timeline)
        data, _, _ = read_export(input_path)
        if hashlib.sha256(data).hexdigest() != inventory["source"]["sha256"]:
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Export changed during preparation"
            )
        source = inventory["source"]
        options = _repair_options(
            predecessor, source, media_roots, mappings, declarations
        )
        import_id = packet_identity(
            source["sha256"],
            source["timelinePointer"],
            self.provider,
            self.workspace.video_id,
            options,
        )
        index_path = self.packet_path(import_id)
        if index_path.exists():
            return self._result("prepare", self.load(import_id), idempotent=True)
        session = {
            "schemaVersion": "1.0.0",
            "normalizerVersion": NORMALIZER_VERSION,
            "importId": import_id,
            "provider": self.provider,
            "videoId": self.workspace.video_id,
            "state": "prepared",
            "source": source,
            "options": options,
            "refs": {},
            "expectedHeadHash": self.head_hash(),
            "actor": str(actor).strip(),
            "reason": str(reason).strip(),
            "createdAt": now_iso(),
        }
        if predecessor is not None:
            session["supersedesImportId"] = predecessor["importId"]
        validate_document(session, _SCHEMA)
        snapshot = {"schemaVersion": "1.0.0", "source": source, "inventory": inventory}
        validate_document(snapshot, _SCHEMA + "#/$defs/snapshot")
        self._check_context()
        try:
            return self._persist_prepared_packet(session, snapshot, data)
        except OSError as exc:
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Preparation was interrupted before canonical selection; retry the same input and options",
                scope=import_id,
            ) from exc

    def _persist_prepared_packet(self, session, snapshot, data):
        import_id = session["importId"]
        index_path = self.packet_path(import_id)
        _immutable_bytes(self.packet_path(import_id, "source.otio"), data)
        snapshot_path = self.packet_path(import_id, "snapshot.json")
        write_immutable_json(snapshot_path, snapshot)
        session["refs"] = {
            "export": self._ref(import_id, self.packet_path(import_id, "source.otio")),
            "snapshot": self._ref(import_id, snapshot_path),
        }
        try:
            write_immutable_json(index_path, session)
        except StoreError:
            if not index_path.is_file():
                raise
            return self._result("prepare", self.load(import_id), idempotent=True)
        return self._result("prepare", session, idempotent=False)

    def _source_path(self, clip, session):
        mapping = session["options"]["mappings"].get(clip["referencePointer"], {})
        chosen = (
            Path(mapping["path"]) if mapping else _local_reference(clip["targetUrl"])
        )
        if not chosen.is_absolute():
            raise ImportError(
                "OTIO_MEDIA_MISSING",
                "Relink this relative media reference explicitly",
                scope=clip["referencePointer"],
            )
        path = chosen.resolve()
        if (
            mapping
            and mapping.get("identityConfirmed") is not True
            and path != _local_reference(clip["targetUrl"]).resolve()
        ):
            raise ImportError(
                "OTIO_MEDIA_AMBIGUOUS",
                "Explicitly confirm the intended identity of this replacement original",
                scope=clip["referencePointer"],
            )
        self._source_boundary(path, mapping, session, clip["referencePointer"])
        return path, mapping

    def _source_boundary(self, path, mapping, session, scope):
        roots = [
            self.workspace.raw_dir.resolve(),
            *(Path(root).resolve() for root in session["options"]["mediaRoots"]),
        ]
        if not mapping and not any(path.is_relative_to(root) for root in roots):
            raise ImportError(
                "OTIO_MEDIA_MISSING",
                "Source is outside declared media roots; supply an explicit file mapping",
                scope=scope,
            )
        if path.is_relative_to(
            (self.workspace.raw_dir / "edit").resolve()
        ) or path.is_relative_to(repo_root().resolve()):
            raise ImportError(
                "OTIO_SOURCE_PROHIBITED",
                "Derived edit files and orchestrator files cannot be originals",
                scope=scope,
            )
        if not path.is_file():
            raise ImportError(
                "OTIO_MEDIA_MISSING",
                "Mapped original file is missing",
                scope=scope,
            )

    def _source_material(self, layout, session, output):
        if "tracks" in layout:
            return self._placed_material(layout, session, output)
        resolved = [self._source_path(clip, session) for clip in layout["clips"]]
        described, fingerprints = self._probe_originals(resolved, layout["clips"])
        sources, segments, clocks = {}, [], {}
        fps = Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
        for clip, (path, mapping) in zip(layout["clips"], resolved, strict=True):
            info = described[path]
            source = self._admit_original(
                path, mapping, info, output, clip, fingerprints[path], clocks=clocks
            )
            sources[source["sourceId"]] = source
            segments.append(
                {
                    "segmentId": "otio-" + content_hash(clip["pointer"])[:24],
                    "sourceId": source["sourceId"],
                    "in": _time_value(clip["start"], source["sourceId"], fps),
                    "out": _time_value(
                        clip["start"] + clip["duration"], source["sourceId"], fps
                    ),
                    "reason": "Preserve exported source interval",
                }
            )
        return {"sources": list(sources.values()), "segments": segments}

    def _placed_material(self, layout, session, output):
        resolved = [self._source_path(clip, session) for clip in layout["clips"]]
        described, fingerprints = self._probe_originals(resolved, layout["clips"])
        sources, placements, clocks = {}, [], {}
        fps = Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
        for clip, (path, mapping) in zip(layout["clips"], resolved, strict=True):
            info = described[path]
            source, kind = self._admit_original(
                path,
                mapping,
                info,
                output,
                clip,
                fingerprints[path],
                placed=True,
                clocks=clocks,
            )
            source_id = source["sourceId"]
            sources[source_id] = source
            placements.append(
                {
                    "placementId": "placement-" + content_hash(clip["pointer"])[:24],
                    "elementId": clip["pointer"],
                    "trackId": clip["trackId"],
                    "sourceId": source_id,
                    "mediaKind": kind,
                    **_placed_raw_bounds(clip, kind, fps, source_id),
                    "start": _program_time(clip["programStart"], fps),
                    "end": _program_time(clip["programStart"] + clip["duration"], fps),
                    "enabled": clip["enabled"],
                    "routing": {
                        key: value
                        for key, value in source["streamMetadata"].items()
                        if key in {"videoStreamIndex", "audioSelection"}
                    },
                    "evidenceOrigin": "export",
                    **_audio_state(mapping, kind, clip["pointer"]),
                }
            )
        gaps = [
            {
                "gapId": "gap-" + content_hash(gap["pointer"])[:24],
                "trackId": gap["trackId"],
                "start": _program_time(gap["programStart"], fps),
                "end": _program_time(gap["programStart"] + gap["duration"], fps),
                "evidenceOrigin": "export",
            }
            for gap in layout["gaps"]
        ]
        return {
            "sources": list(sources.values()),
            "layoutMode": "placed",
            "layout": {
                "programClock": {
                    "frameRate": output["frameRate"],
                    "timebase": {"num": fps.denominator, "den": fps.numerator},
                    "audioSampleRate": output["audioSampleRate"],
                },
                "duration": _program_time(layout["duration"], fps),
                "displayOrigin": layout["globalStart"],
                "background": "black",
                "tracks": layout["tracks"],
                "placements": placements,
                "gaps": gaps,
            },
        }

    def _placed_streams(self, path, mapping, info, clip, output):
        kind = clip["mediaKind"]
        scope = clip["referencePointer"]
        if kind == "audio":
            selection = deepcopy(mapping.get("audioSelection") or {})
            stream = _selected_stream(
                info["streams"], selection.get("streamIndex"), "audio", scope
            )
            _audio_selection(selection, stream, scope)
            selection["sourceSampleRate"] = stream["sampleRate"]
            metadata = {"audioSelection": selection}
        else:
            stream = _selected_stream(
                info["streams"], mapping.get("videoStreamIndex"), "video", scope
            )
            metadata = {"videoStreamIndex": stream["index"]}
            if mapping.get("mediaKind") == "still":
                kind = "still"
                self._verify_still(path, scope)
            elif not _matching_cfr(
                stream, Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
            ):
                raise ImportError(
                    "OTIO_RATE_UNVERIFIED",
                    "Placed moving picture requires verified matching CFR",
                    scope=scope,
                )
            _square_picture(stream, scope)
        return metadata, stream, kind

    def _local_probe(self, paths, scope):
        if self.probe is None:
            raise ImportError(
                "OTIO_RUNTIME_UNAVAILABLE",
                "An original-media probe is required",
                scope=scope,
            )
        try:
            inventory = self.probe(paths)
        except ImportError:
            raise
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            raise ImportError(
                "OTIO_RUNTIME_UNAVAILABLE",
                "Original-media probing failed or timed out; check the local tool and original file",
                scope=scope,
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ImportError(
                "OTIO_ROUTING_UNVERIFIED",
                "The local original-media probe returned invalid properties",
                scope=scope,
            ) from exc
        return inventory

    def _probe_originals(self, resolved, clips):
        scope = clips[0]["referencePointer"]
        paths = sorted({path for path, _ in resolved})
        inventory = self._local_probe(paths, scope)
        try:
            described = {
                Path(item["locator"]).resolve(): item for item in inventory["sources"]
            }
            if set(described) != set(paths) or len(inventory["sources"]) != len(paths):
                raise ValueError(
                    "Probe did not describe exactly the selected originals"
                )
            fingerprints = {path: file_fingerprint(path) for path in paths}
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Cannot verify the selected original inventory",
                scope=scope,
            ) from exc
        self._reject_derived_originals(fingerprints, scope)
        return described, fingerprints

    def _reject_derived_originals(self, fingerprints, scope):
        from .media_admission import MediaAdmissionError, require_no_forbidden_outputs
        from .migration import inventory_historical_output_fingerprints

        try:
            require_no_forbidden_outputs(
                [
                    {**value, "locator": str(path)}
                    for path, value in fingerprints.items()
                ],
                known_outputs=inventory_historical_output_fingerprints(
                    self.workspace.raw_dir, timeline_dir=self.workspace.timeline_dir
                ),
            )
        except MediaAdmissionError as exc:
            finding = exc.finding
            raise ImportError(
                "OTIO_SOURCE_PROHIBITED",
                f"Prohibited original {finding['locator']}: bytes belong to a retained {finding['outputRole']} output",
                scope=scope,
            ) from exc
        except (OSError, ValueError) as exc:
            raise ImportError(
                "OTIO_SOURCE_PROHIBITED",
                f"Cannot verify retained output provenance: {exc}",
                scope=scope,
            ) from exc

    def _admit_original(
        self, path, mapping, info, output, clip, actual, *, placed=False, clocks=None
    ):
        scope = clip["referencePointer"]
        selected = mapping.get("fingerprint")
        if selected and any(
            selected[key] != actual[key] for key in ("sha256", "sizeBytes")
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Selected original bytes differ from the explicit mapping lock",
                scope=scope,
            )
        try:
            if placed:
                source, kind = self._placed_source(
                    path, mapping, info, clip, output, actual
                )
            else:
                source = self._verified_source(
                    path, mapping, info, output, clip, actual
                )
                kind = "video"
            if kind == "video":
                source["streamMetadata"]["videoClock"] = self._video_clock(
                    path, info, source, output, scope, clocks
                )
                self._video_extent(clip, output, source["streamMetadata"]["videoClock"])
            return (source, kind) if placed else source
        except ImportError:
            raise
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise ImportError(
                "OTIO_ROUTING_UNVERIFIED",
                "Selected media properties are missing or invalid; repair this reference and validate again",
                scope=scope,
            ) from exc

    @staticmethod
    def _video_extent(clip, output, evidence):
        fps = Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
        end = max(clip["start"] + clip["duration"], clip["availableDuration"] or 0)
        count = evidence.get("packetCount")
        if type(count) is not int or count <= 0 or end * fps > count:
            raise ImportError(
                "OTIO_RATE_UNVERIFIED",
                "Exported source range exceeds verified available picture frames",
                scope=clip["referencePointer"],
            )

    def _video_clock(self, path, info, source, output, scope, clocks):
        index = source["streamMetadata"]["videoStreamIndex"]
        fps = Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
        key = (path, source["fingerprint"]["sha256"], index, fps)
        if clocks is not None and key in clocks:
            return deepcopy(clocks[key])
        stream = _selected_stream(info["streams"], index, "video", scope)
        try:
            evidence = self._clock_evidence(path, stream, source, fps)
            if (
                evidence.get("status") != "verified"
                or evidence.get("sourceSha256") != source["fingerprint"]["sha256"]
                or evidence.get("streamIndex") != index
                or evidence.get("frameRate") != output["frameRate"]
            ):
                raise ValueError("Clock evidence differs from selected source")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            raise ImportError(
                "OTIO_RATE_UNVERIFIED",
                f"Cannot verify the complete original video clock: {exc}",
                scope=scope,
            ) from exc
        if clocks is not None:
            clocks[key] = deepcopy(evidence)
        return evidence

    def _clock_evidence(self, path, stream, source, fps):
        if self.clock_probe is None:
            # Injected inventory ports may supply evidence; the native inventory
            # strips opaque fields and always uses its bound clock verifier.
            evidence = stream.get("clockVerification")
            if not isinstance(evidence, dict):
                raise ValueError("Whole-stream packet clock verification is required")
            return deepcopy(evidence)
        return self.clock_probe(
            path,
            stream["index"],
            fps,
            time_base=stream["timeBase"],
            expected_sha256=source["fingerprint"]["sha256"],
            expected_frames=stream.get("frameCount"),
            start_ticks=stream.get("startTicks"),
        )

    def _placed_source(self, path, mapping, info, clip, output, actual):
        if any(
            info["fingerprint"][key] != actual[key] for key in ("sha256", "sizeBytes")
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Original changed during probing",
                scope=clip["pointer"],
            )
        metadata, stream, kind = self._placed_streams(path, mapping, info, clip, output)
        scope = clip["referencePointer"]
        if kind != "still":
            _probed_seconds(stream, "start", scope)
            end = clip["start"] + clip["duration"]
            exported_extent = clip["availableDuration"] or end
            if max(end, exported_extent) > _probed_seconds(stream, "duration", scope):
                raise ImportError(
                    "OTIO_SOURCE_CHANGED",
                    "Placement exceeds selected stream extent",
                    scope=scope,
                )
        source_id = (
            "source-"
            + content_hash(
                {"path": str(path), "sha256": actual["sha256"], "streams": metadata}
            )[:24]
        )
        return {
            "sourceId": source_id,
            "kind": "raw",
            "locator": str(path),
            "fingerprint": actual,
            "streamMetadata": metadata,
        }, kind

    def _verify_still(self, path, scope):
        if self.still_probe is None:
            raise ImportError(
                "OTIO_RUNTIME_UNAVAILABLE",
                "Literal still verification is required",
                scope=scope,
            )
        try:
            evidence = self.still_probe(path)
        except (OSError, ValueError, RuntimeError) as exc:
            raise ImportError(
                "OTIO_ROUTING_UNVERIFIED",
                f"Cannot verify a single original image: {exc}",
                scope=scope,
            ) from exc
        if evidence.get("decodedFrameCount") != 1:
            raise ImportError(
                "OTIO_ROUTING_UNVERIFIED",
                "Still content must decode exactly one image",
                scope=scope,
            )

    def _verified_source(self, path, mapping, info, output, clip, actual):
        if any(
            info["fingerprint"][key] != actual[key] for key in ("sha256", "sizeBytes")
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Source changed while being probed",
                scope=clip["referencePointer"],
            )
        duration = Fraction(str(info["durationSeconds"]))
        if (
            clip["start"] + clip["duration"] > duration
            or clip["availableDuration"] > duration
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Exported source range exceeds the selected original",
                scope=clip["pointer"],
            )
        metadata = _stream_selection(mapping, info, output, clip["pointer"])
        _linked_stream_bounds(info, metadata, clip)
        source_id = (
            "source-"
            + content_hash(
                {"path": str(path), "sha256": actual["sha256"], "streams": metadata}
            )[:24]
        )
        return {
            "sourceId": source_id,
            "kind": "raw",
            "locator": str(path),
            "fingerprint": actual,
            "streamMetadata": metadata,
        }

    def _proposal(self, session, checks):
        import_id = session["importId"]
        if session["normalizerVersion"] != NORMALIZER_VERSION:
            raise ImportError(
                "OTIO_RUNTIME_UNAVAILABLE",
                "Reprepare this export with the current version-bound interpreter; prior canonical edits remain available",
            )
        if self.reader is None:
            raise ImportError(
                "OTIO_RUNTIME_UNAVAILABLE",
                "The isolated resolve-import native reader is required",
            )
        data = self.read_ref(import_id, session["refs"]["export"])
        declarations = session["options"]["declarations"]
        output = _declared_output(declarations, session["source"])
        native = self.reader(data)
        normalizer = (
            normalize_placed
            if declarations.get("layoutMode") == "placed"
            else normalize_contiguous
        )
        if normalizer is normalize_placed and output["audioSampleRate"] != 48000:
            raise ImportError(
                "OTIO_ROUTING_UNVERIFIED",
                "Placed source audio currently requires 48000 Hz output",
            )
        layout = normalizer(
            data,
            native,
            session["source"]["timelinePointer"],
            declarations,
        )
        checks["semanticValidation"] = "passed"
        checks["mediaReady"] = "failed"
        snapshot = self._source_material(layout, session, output)
        if snapshot.get("layoutMode") == "placed":
            from .import_layout import LayoutError, validate_layout_content

            try:
                validate_layout_content(
                    snapshot, {**output, "displayOrigin": layout["globalStart"]}
                )
            except LayoutError as exc:
                raise ImportError("OTIO_RATE_UNVERIFIED", str(exc)) from exc
        checks["mediaReady"] = "passed"
        return {
            "schemaVersion": "1.0.0",
            "importId": import_id,
            "snapshot": snapshot,
            "output": {**output, "displayOrigin": layout["globalStart"]},
            "findings": [],
            "provisionalFinishing": [],
        }

    def _sync_lock(self, proposal):
        if not self.workspace.artifact_path("sync-map").is_file():
            return None
        store = self.workspace.store("sync-map")
        index = store.load_index()
        approval = store.effective_approval()
        if not approval or index["activeState"] != "valid":
            return None
        revision = store.revision(index["headRevisionId"])
        snapshot = revision["snapshot"]
        expected = {
            s["sourceId"]: s["fingerprint"]["sha256"]
            for s in proposal["snapshot"]["sources"]
        }
        if (
            snapshot.get("status") != "not-applicable"
            or snapshot.get("rawFingerprints") != expected
            or approval.get("dependencyHashes") != expected
        ):
            return None
        return {
            "revisionHash": revision["contentHash"],
            "decisionHash": content_hash(approval),
        }

    def _validation(self, session):
        proposal = {
            "schemaVersion": "1.0.0",
            "importId": session["importId"],
            "snapshot": {},
            "output": {},
            "findings": [],
            "provisionalFinishing": [],
        }
        findings = []
        checks = {"semanticValidation": "not-checked", "mediaReady": "not-checked"}
        try:
            proposal = self._proposal(session, checks)
            _require_source_only_proposal(proposal)
        except ImportError as exc:
            findings.append(_finding(exc))
            if checks["semanticValidation"] == "not-checked":
                checks["semanticValidation"] = (
                    "not-ready" if exc.code == "OTIO_RUNTIME_UNAVAILABLE" else "failed"
                )
        media_mappings, media_findings = self._media_report(session, proposal, checks)
        findings.extend(media_findings)
        elements, accounting, element_findings = self._element_report(session, checks)
        findings.extend(element_findings)
        attempted = not findings
        sync = self._sync_lock(proposal) if attempted else None
        head = self.head_hash()
        state = (
            "blocked" if findings else "ready-to-activate" if sync else "awaiting-sync"
        )
        proposal["elements"] = elements
        proposal["findings"] = deepcopy(findings)
        proposal["activeEditDiff"] = self._active_edit_diff(proposal, head)
        checks = _checked_readiness(checks, sync, attempted=attempted, state=state)
        locks = {
            "expectedHeadHash": head,
            "proposalHash": content_hash(proposal),
            "sync": sync,
            "source": session["source"],
            "checks": checks,
            "context": self.context_lock,
            "elementAccounting": accounting,
            "activeEditDiffHash": content_hash(proposal["activeEditDiff"]),
        }
        receipt = {
            "schemaVersion": "1.0.0",
            "importId": session["importId"],
            "state": state,
            "locks": locks,
            "findings": findings,
            "ready": state == "ready-to-activate",
            "mediaMappings": media_mappings,
        }
        validate_document(proposal, _SCHEMA + "#/$defs/proposal")
        validate_document(receipt, _SCHEMA + "#/$defs/validation")
        return proposal, receipt

    def _active_edit_diff(self, proposal, head):
        from .cmap_service import CMapService

        if not proposal["snapshot"].get("sources"):
            return []
        parent = None
        if head != "empty":
            store = self.workspace.store("cmap")
            parent = store.revision(store.load_index()["headRevisionId"])["snapshot"]
        diff = CMapService._diff(parent, proposal["snapshot"], "Select imported draft")
        previous = (parent or {}).get("importOutput")
        if parent and previous != proposal["output"]:
            diff.append(
                {
                    "operation": "change-import-output",
                    "before": previous,
                    "after": deepcopy(proposal["output"]),
                    "reason": "Explicitly select declared imported canvas and clocks",
                }
            )
        return diff

    def _element_report(self, session, checks):
        from .import_findings import account_elements

        data = self.read_ref(session["importId"], session["refs"]["export"])
        return account_elements(
            data,
            session["source"]["timelinePointer"],
            checks=checks,
            declarations=session["options"]["declarations"],
        )

    def _media_report(self, session, proposal, checks):
        snapshot = self.read_ref(session["importId"], session["refs"]["snapshot"])
        references = [
            item
            for item in snapshot["inventory"]["references"]
            if item.get("active") is True
        ]
        if checks.get("mediaReady") == "passed":
            return _verified_mappings(references, proposal["snapshot"])
        if checks.get("mediaReady") != "failed":
            return {}, []
        from .import_relink import discover_candidates

        return discover_candidates(
            references,
            session["options"]["mediaRoots"],
            probe=self.probe,
            prohibited_roots=(self.workspace.raw_dir / "edit", repo_root()),
        )

    def _record(self, import_id, category, value):
        path = self.packet_path(import_id, f"{category}/{content_hash(value)}.json")
        write_immutable_json(path, value)
        return self._ref(import_id, path)

    def _save(self, session):
        validate_document(session, _SCHEMA)
        atomic_write_json(self.packet_path(session["importId"]), session)

    def _validation_result(self, session, proposal, receipt):
        return self._result(
            "validate",
            session,
            status=receipt["state"],
            proposal=proposal,
            validation=receipt,
            validationHash=content_hash(receipt),
            activeEditDiff=proposal.get("activeEditDiff", []),
            findings=receipt["findings"],
            mediaMappings=receipt.get("mediaMappings", {}),
            elements=proposal.get("elements", []),
            summary={
                "elementAccounting": receipt["locks"]["elementAccounting"],
                "findingCounts": {
                    "total": len(receipt["findings"]),
                    **dict(Counter(finding["code"] for finding in receipt["findings"])),
                },
            },
            readiness={
                "inspectionComplete": True,
                **receipt["locks"]["checks"],
                "activationAllowed": receipt["ready"],
                "reviewState": "not-started",
            },
        )

    def validate(self, import_id):
        with timeline_writer(self.workspace.timeline_dir):
            self._check_context()
            session = self.load(import_id)
            proposal, receipt = self._validation(session)
            self._check_context()
            session["refs"]["proposal"] = self._record(import_id, "proposals", proposal)
            session["refs"]["validation"] = self._record(
                import_id, "validations", receipt
            )
            session["state"] = (
                "unresolved" if receipt["state"] == "blocked" else receipt["state"]
            )
            self._save(session)
            return self._validation_result(session, proposal, receipt)

    def _activation_receipt(self, session, validation_hash):
        receipt = self._versioned_document(
            session["importId"], "validations", validation_hash, "validation"
        )
        if receipt["importId"] != session["importId"] or not receipt["ready"]:
            raise ImportError(
                "OTIO_TARGET_CONFLICT", "Exact ready validation receipt is required"
            )
        proposal = self._versioned_document(
            session["importId"],
            "proposals",
            receipt["locks"]["proposalHash"],
            "proposal",
        )
        if (
            proposal["importId"] != session["importId"]
            or content_hash(proposal) != receipt["locks"]["proposalHash"]
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Staged proposal differs from the exact accepted validation",
            )
        _require_source_only_proposal(proposal)
        return receipt, proposal

    def _versioned_document(self, import_id, category, digest, schema):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ImportError(
                "OTIO_INPUT_INVALID", "An exact immutable evidence hash is required"
            )
        try:
            value = _document(self.packet_path(import_id, f"{category}/{digest}.json"))
            validate_document(value, _SCHEMA + "#/$defs/" + schema)
        except (OSError, ValueError) as exc:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Required immutable import evidence is missing or invalid",
            ) from exc
        if content_hash(value) != digest:
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Immutable import evidence hash differs"
            )
        return value

    def _activation_intent(
        self, session, validation_hash, expected_head, actor, reason
    ):
        operation_id = content_hash(
            {
                "importId": session["importId"],
                "validationHash": validation_hash,
                "expectedHeadHash": expected_head,
            }
        )
        path = self.packet_path(session["importId"], f"activation/{operation_id}.json")
        if path.is_file():
            intent = _document(path)
            validate_document(intent, _SCHEMA + "#/$defs/activation")
            expected = {
                "operationId": operation_id,
                "importId": session["importId"],
                "validationHash": validation_hash,
                "expectedHeadHash": expected_head,
                "revisionId": "cmap-import-" + operation_id[:24],
                "phase": "prepared",
            }
            if any(intent.get(key) != value for key, value in expected.items()):
                raise ImportError(
                    "OTIO_SOURCE_CHANGED",
                    "Activation intent does not match its derived operation",
                )
            self._verify_previous_intent(intent)
            return intent
        if self.head_hash() != expected_head:
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "The selected CMap head changed; inspect and validate the current edit",
            )
        previous = None
        if expected_head != "empty":
            store = self.workspace.store("cmap")
            previous = store.revision(store.load_index()["headRevisionId"])
        intent = {
            "schemaVersion": "1.0.0",
            "operationId": operation_id,
            "importId": session["importId"],
            "phase": "prepared",
            "expectedHeadHash": expected_head,
            "validationHash": validation_hash,
            "actor": actor,
            "reason": reason,
            "createdAt": now_iso(),
            "revisionId": "cmap-import-" + operation_id[:24],
            "previousRevisionId": previous["revisionId"] if previous else None,
            "previousSnapshot": previous["snapshot"] if previous else None,
        }
        validate_document(intent, _SCHEMA + "#/$defs/activation")
        write_immutable_json(path, intent)
        return intent

    def _verify_previous_intent(self, intent):
        previous_id = intent["previousRevisionId"]
        if intent["expectedHeadHash"] == "empty":
            valid = previous_id is None and intent["previousSnapshot"] is None
        elif previous_id is None or intent["previousSnapshot"] is None:
            valid = False
        else:
            previous = self.workspace.store("cmap").revision(previous_id)
            valid = (
                previous["contentHash"] == intent["expectedHeadHash"]
                and previous["snapshot"] == intent["previousSnapshot"]
            )
        if not valid:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Activation prior-state evidence differs from the exact expected canonical head",
            )

    def _selected_snapshot(self, session, proposal, intent):
        snapshot = deepcopy(proposal["snapshot"])
        snapshot["sourceAssemblyPolicy"] = "preserve-import"
        snapshot["importOutput"] = deepcopy(proposal["output"])
        snapshot["originRef"] = {
            "importId": session["importId"],
            "exportSha256": session["source"]["sha256"],
            "timelinePointer": session["source"]["timelinePointer"],
            "proposalSha256": self._ref(
                session["importId"],
                self.packet_path(
                    session["importId"], f"proposals/{content_hash(proposal)}.json"
                ),
            )["sha256"],
            "capabilityVersion": "placed-1.0.0"
            if snapshot.get("layoutMode") == "placed"
            else "contiguous-1.0.0",
            "activationId": intent["operationId"],
        }
        return snapshot

    def _activation_revision(self, intent):
        store = self.workspace.store("cmap")
        if not store.path.is_file():
            return None
        refs = store.load_index()["revisionRefs"]
        if any(row["revisionId"] == intent["revisionId"] for row in refs):
            return store.revision(intent["revisionId"])
        return None

    def _check_committed_selection(self, session, intent, proposal, revision):
        actual = deepcopy(revision["snapshot"])
        actual.pop("syncRef", None)
        if actual != self._selected_snapshot(session, proposal, intent):
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Activation does not match its committed canonical revision",
            )
        self._verify_previous_intent(intent)
        if revision["parentRevisionId"] != intent["previousRevisionId"]:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Activation parent differs from the recorded prior head",
            )

    def _historical_activation(self, session, intent, proposal, revision):
        from .import_evidence import verify_import_origin

        self._check_committed_selection(session, intent, proposal, revision)
        verify_import_origin(self.workspace, revision)
        store = self.workspace.store("cmap")
        current = store.revision(store.load_index()["headRevisionId"])
        origin = current["snapshot"].get("originRef") or {}
        return self._result(
            "activate",
            session,
            status="active-draft"
            if origin.get("activationId") == intent["operationId"]
            else "superseded",
            revision=current,
            activation={
                **intent,
                "phase": "reconciled",
                "revisionHash": revision["contentHash"],
            },
            idempotent=True,
        )

    def _reconcile_activation(self, session, intent, proposal):
        store = self.workspace.store("cmap")
        revision = store.revision(store.load_index()["headRevisionId"])
        if revision["revisionId"] != intent["revisionId"]:
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Pending activation is not the current canonical head",
            )
        self._check_committed_selection(session, intent, proposal, revision)
        self._reconcile_selected_draft(intent, revision)
        completed = {
            **intent,
            "phase": "reconciled",
            "revisionHash": revision["contentHash"],
        }
        session["refs"]["activation"] = self._record(
            session["importId"], "activation-results", completed
        )
        session["state"] = "active-draft"
        self._save(session)
        self.workspace.notify_editlog()
        self._close_activation(session, intent, proposal, revision)
        self._pending_path().unlink(missing_ok=True)
        return self._result(
            "activate", session, activation=completed, revision=revision
        )

    def _close_activation(self, session, intent, proposal, revision):
        from .import_evidence import verify_import_origin

        receipt, _ = self._activation_receipt(session, intent["validationHash"])
        self._check_context()
        self._verify_committed_basis(proposal, receipt)
        verify_import_origin(self.workspace, revision)
        self._check_pending(intent)

    def _reconcile_selected_draft(self, intent, revision):
        from .lifecycle import PipelineRunStore

        if intent["expectedHeadHash"] != "empty":
            self.workspace.invalidate_descendants(
                "cmap",
                before_hash=intent["expectedHeadHash"],
                after_hash=revision["contentHash"],
                reason="CMap revision changed",
                actor=intent["actor"],
                idempotent=True,
            )
        sync = self.workspace.store("sync-map")
        sync_revision = sync.revision(sync.load_index()["headRevisionId"])
        refs = {
            "rawInventory": {"sources": deepcopy(revision["snapshot"]["sources"])},
            "syncRevisionId": sync_revision["revisionId"],
            "syncRevisionHash": sync_revision["contentHash"],
            "cmapRevisionId": revision["revisionId"],
            "cmapRevisionHash": revision["contentHash"],
        }
        PipelineRunStore(self.workspace.pipeline_run_path).reconcile_import_draft(
            activation_id=intent["operationId"],
            cmap_revision_id=revision["revisionId"],
            cmap_revision_hash=revision["contentHash"],
            active_refs=refs,
            actor=intent["actor"],
            reason="Select validated imported draft",
        )

    def _pending_path(self):
        return self.workspace.timeline_dir / "import-activation.pending.json"

    def _check_pending(self, intent):
        path = self._pending_path()
        if path.exists() or path.is_symlink():
            try:
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_size > 4096
                ):
                    raise ValueError("Unverified recovery marker")
                pending = _document(path)
            except (OSError, ValueError) as exc:
                raise ImportError(
                    "OTIO_RECOVERY_REQUIRED",
                    "Pending import marker is unreadable or invalid; restore the exact recovery record before selecting an edit",
                ) from exc
            if pending != {
                "importId": intent["importId"],
                "operationId": intent["operationId"],
            }:
                raise ImportError(
                    "OTIO_RECOVERY_REQUIRED",
                    "Another import activation requires reconciliation",
                )

    def activate(self, import_id, *, validation_hash, expected_head, actor, reason):
        actor, reason = str(actor).strip(), str(reason).strip()
        if not actor or not reason:
            raise ImportError(
                "OTIO_INPUT_INVALID", "Activation actor and reason are required"
            )
        with timeline_writer(self.workspace.timeline_dir, recovery=True):
            self._check_context()
            session = self.load(import_id)
            receipt, proposal = self._activation_receipt(session, validation_hash)
            if receipt["locks"]["expectedHeadHash"] != expected_head:
                raise ImportError(
                    "OTIO_TARGET_CONFLICT",
                    "Activation requires the exact displayed target head",
                )
            try:
                intent = self._activation_intent(
                    session, validation_hash, expected_head, actor, reason
                )
            except OSError as exc:
                raise ImportError(
                    "OTIO_RECOVERY_REQUIRED",
                    "Activation intent was interrupted before selection; retry the exact operation",
                ) from exc
            self._check_pending(intent)
            committed = self._activation_revision(intent)
            if committed is not None:
                self._verify_committed_basis(proposal, receipt)
                if self._pending_path().exists():
                    return self._reconcile_activation(session, intent, proposal)
                return self._historical_activation(session, intent, proposal, committed)
            return self._activate_uncommitted(session, receipt, proposal, intent)

    def _activate_uncommitted(self, session, receipt, proposal, intent):
        if self.head_hash() != intent["expectedHeadHash"]:
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "CMap changed after validation; inspect and validate the current edit",
            )
        current_proposal, current = self._validation(session)
        self._check_context()
        if current != receipt or current_proposal != proposal:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Source, Sync, proposal or target changed; validate again",
            )
        return self._commit_activation(session, receipt, proposal, intent)

    def _clear_uncommitted_pending(self, intent):
        try:
            if self._activation_revision(intent) is not None:
                return
            marker = self._pending_path()
            if marker.is_symlink():
                return
            expected = {
                "importId": intent["importId"],
                "operationId": intent["operationId"],
            }
            if marker.is_file() and _document(marker) == expected:
                marker.unlink()
        except (OSError, ValueError, RuntimeError):
            # An uncertain selection remains guarded until exact recovery.
            return

    def _commit_activation(self, session, receipt, proposal, intent):
        from .cmap_service import CMapService

        try:
            atomic_write_json(
                self._pending_path(),
                {"importId": session["importId"], "operationId": intent["operationId"]},
            )
            self._check_context()
            CMapService(self.workspace).author(
                self._selected_snapshot(session, proposal, intent),
                actor=intent["actor"],
                reason=intent["reason"],
                expected_head_hash=intent["expectedHeadHash"],
                revision_id=intent["revisionId"],
                created_at=intent["createdAt"],
            )
            self._verify_committed_basis(proposal, receipt)
            return self._reconcile_activation(session, intent, proposal)
        except Exception as exc:
            self._clear_uncommitted_pending(intent)
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Import selection was interrupted; retry this exact operation. A committed revision remains guarded until originals and bookkeeping are coherent",
                scope=intent["revisionId"],
            ) from exc

    def _verify_committed_sources(self, proposal):
        with fingerprint_stage(verify_on_exit=True):
            self._verify_original_bytes(proposal)

    def _verify_original_bytes(self, proposal):
        fingerprints = {}
        for source in proposal["snapshot"]["sources"]:
            path = Path(source["locator"])
            actual = file_fingerprint(path)
            if actual["sha256"] != source["fingerprint"]["sha256"]:
                raise ImportError(
                    "OTIO_SOURCE_CHANGED",
                    "Committed import original bytes changed",
                    scope=source["sourceId"],
                )
            fingerprints[path] = actual
        self._reject_derived_originals(fingerprints, "original-media")

    def _verify_committed_basis(self, proposal, receipt):
        if (
            self._pending_path().exists()
            and receipt["locks"]["context"] != self.context_lock
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Pending activation context changed; restore the exact declared target before recovery",
            )
        self._verify_committed_sources(proposal)
        if self._sync_lock(proposal) != receipt["locks"]["sync"]:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Committed import Sync basis changed; revalidate the current edit",
            )

    def _return_target(self, activation_id):
        from .import_evidence import verify_import_origin

        if not isinstance(activation_id, str) or not re.fullmatch(
            r"[a-f0-9]{64}", activation_id
        ):
            raise ImportError(
                "OTIO_INPUT_INVALID", "Return requires an exact activation ID"
            )
        store = self.workspace.store("cmap")
        current = store.load_index()["headRevisionId"]
        seen = set()
        while current and current not in seen:
            seen.add(current)
            revision = store.revision(current)
            origin = revision["snapshot"].get("originRef") or {}
            if origin.get("activationId") == activation_id:
                verify_import_origin(self.workspace, revision)
                return self._recorded_return_target(origin)
            current = revision["parentRevisionId"]
        raise ImportError(
            "OTIO_TARGET_CONFLICT",
            "The activation is not in the current canonical history",
        )

    def _recorded_return_target(self, origin):
        session = self.load(origin["importId"])
        path = self.packet_path(
            session["importId"], f"activation/{origin['activationId']}.json"
        )
        activation = _document(path)
        validate_document(activation, _SCHEMA + "#/$defs/activation")
        if activation["previousRevisionId"] is None:
            raise ImportError(
                "OTIO_TARGET_CONFLICT",
                "This activation has no prior editable content; return never deletes the canonical head",
            )
        target = self.workspace.store("cmap").revision(activation["previousRevisionId"])
        if (
            target["snapshot"] != activation["previousSnapshot"]
            or target["contentHash"] != activation["expectedHeadHash"]
        ):
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "Recorded prior selection differs from canonical history",
            )
        return session, target

    def _return_basis(self, target, intent=None):
        from .import_evidence import verify_import_origin

        verify_import_origin(self.workspace, target)
        proposal = {"snapshot": target["snapshot"]}
        self._verify_committed_sources(proposal)
        sync = self._sync_lock(proposal)
        if sync is None:
            raise ImportError(
                "OTIO_SYNC_REQUIRED",
                "Return requires current approved Sync/N/A for the prior originals",
            )
        if intent is not None and sync != intent["sync"]:
            raise ImportError(
                "OTIO_SOURCE_CHANGED",
                "The return operation's current Sync basis changed",
            )
        return sync

    def _return_intent(
        self, session, target, activation_id, expected_head, actor, reason
    ):
        operation = content_hash(
            {
                "kind": "return",
                "activationId": activation_id,
                "expectedHeadHash": expected_head,
            }
        )
        path = self.packet_path(session["importId"], f"returns/{operation}.json")
        expected = {
            "schemaVersion": "1.0.0",
            "kind": "return",
            "phase": "prepared",
            "operationId": operation,
            "activationId": activation_id,
            "importId": session["importId"],
            "expectedHeadHash": expected_head,
            "targetRevisionId": target["revisionId"],
            "targetRevisionHash": target["contentHash"],
            "revisionId": "cmap-return-" + operation[:24],
        }
        if path.is_file():
            intent = _document(path)
            validate_document(intent, _SCHEMA + "#/$defs/returnIntent")
            if any(intent[key] != value for key, value in expected.items()):
                raise ImportError(
                    "OTIO_SOURCE_CHANGED",
                    "Return intent differs from the requested canonical selection",
                )
        else:
            if self.head_hash() != expected_head:
                raise ImportError(
                    "OTIO_TARGET_CONFLICT",
                    "Return requires the exact current CMap head",
                )
            intent = {
                **expected,
                "actor": actor,
                "reason": reason,
                "createdAt": now_iso(),
                "sync": self._return_basis(target),
            }
            validate_document(intent, _SCHEMA + "#/$defs/returnIntent")
            write_immutable_json(path, intent)
        return intent, path

    def _verify_return_revision(self, target, intent, revision):
        actual, expected = deepcopy(revision["snapshot"]), deepcopy(target["snapshot"])
        sync = actual.pop("syncRef", {})
        expected.pop("syncRef", None)
        parent = self.workspace.store("cmap").revision(revision["parentRevisionId"])
        if (
            actual != expected
            or sync.get("contentSha256") != intent["sync"]["revisionHash"]
            or parent["contentHash"] != intent["expectedHeadHash"]
        ):
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Committed return differs from its prior content and current Sync",
            )

    def _reconcile_return(self, session, target, intent, revision):
        self._verify_return_revision(target, intent, revision)
        if self.head_hash() != revision["contentHash"]:
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Pending return is not the current canonical selection",
            )
        self._reconcile_selected_draft(intent, revision)
        completed = {
            **intent,
            "phase": "reconciled",
            "revisionHash": revision["contentHash"],
        }
        session["refs"]["return"] = self._record(
            session["importId"], "return-results", completed
        )
        session["state"] = "superseded"
        self._save(session)
        self.workspace.notify_editlog()
        self._close_return(target, intent, revision)
        self._pending_path().unlink(missing_ok=True)
        return self._result(
            "rollback",
            session,
            status="active-draft",
            revision=revision,
            activation=completed,
        )

    def _close_return(self, target, intent, revision):
        from .import_evidence import verify_import_origin
        from .import_retention import retained_return_paths

        self._check_context()
        self._return_basis(target, intent)
        verify_import_origin(self.workspace, revision)
        retained_return_paths(self.workspace, revision)
        self._check_pending(intent)

    def _historical_return(self, session, target, intent, revision):
        self._verify_return_revision(target, intent, revision)
        completed = {
            **intent,
            "phase": "reconciled",
            "revisionHash": revision["contentHash"],
        }
        result = self._versioned_document(
            session["importId"],
            "return-results",
            content_hash(completed),
            "returnIntent",
        )
        if result != completed:
            raise ImportError(
                "OTIO_SOURCE_CHANGED", "Return reconciliation evidence differs"
            )
        store = self.workspace.store("cmap")
        current = store.revision(store.load_index()["headRevisionId"])
        return self._result(
            "rollback",
            session,
            status="active-draft"
            if current["snapshot"].get("originRef")
            == target["snapshot"].get("originRef")
            else "superseded",
            revision=current,
            activation=completed,
            idempotent=True,
        )

    def _commit_return(self, session, target, intent, path):
        from .cmap_service import CMapService

        reference = self._ref(session["importId"], path)
        evidence = [
            {
                "evidenceId": "return-" + intent["operationId"],
                "kind": "timeline-import-return",
                "path": path.relative_to(self.workspace.timeline_dir).as_posix(),
                "sha256": reference["sha256"],
            }
        ]
        try:
            atomic_write_json(
                self._pending_path(),
                {"importId": session["importId"], "operationId": intent["operationId"]},
            )
            self._check_context()
            revision = CMapService(self.workspace).author(
                target["snapshot"],
                actor=intent["actor"],
                reason=intent["reason"],
                expected_head_hash=intent["expectedHeadHash"],
                revision_id=intent["revisionId"],
                created_at=intent["createdAt"],
                evidence=evidence,
            )
            self._return_basis(target, intent)
            return self._reconcile_return(session, target, intent, revision)
        except Exception as exc:
            self._clear_uncommitted_pending(intent)
            raise ImportError(
                "OTIO_RECOVERY_REQUIRED",
                "Return was interrupted; retry the exact activation ID and expected head to reconcile",
                scope=intent["revisionId"],
            ) from exc

    def rollback(self, activation_id, *, expected_head, actor, reason):
        actor, reason = str(actor).strip(), str(reason).strip()
        if not actor or not reason:
            raise ImportError(
                "OTIO_INPUT_INVALID", "Return actor and reason are required"
            )
        if not isinstance(expected_head, str) or not re.fullmatch(
            r"[a-f0-9]{64}", expected_head
        ):
            raise ImportError(
                "OTIO_INPUT_INVALID",
                "Return requires the exact nonempty CMap head hash",
            )
        with timeline_writer(self.workspace.timeline_dir, recovery=True):
            self._check_context()
            session, target = self._return_target(activation_id)
            try:
                intent, path = self._return_intent(
                    session, target, activation_id, expected_head, actor, reason
                )
            except OSError as exc:
                raise ImportError(
                    "OTIO_RECOVERY_REQUIRED",
                    "Return intent was interrupted before selection; retry the same activation ID and expected head",
                ) from exc
            self._check_pending(intent)
            self._return_basis(target, intent)
            committed = self._activation_revision(intent)
            if committed is not None:
                if self._pending_path().exists():
                    return self._reconcile_return(session, target, intent, committed)
                return self._historical_return(session, target, intent, committed)
            if self.head_hash() != expected_head:
                raise ImportError(
                    "OTIO_TARGET_CONFLICT", "CMap changed before return selection"
                )
            return self._commit_return(session, target, intent, path)

    def _status_selection(self):
        store = self.workspace.store("cmap")
        if not store.path.is_file():
            return None, None
        head = store.load_index()["headRevisionId"]
        if head is None:
            return None, None
        revision = store.revision(head)
        return revision["snapshot"].get("originRef"), {
            "revisionId": revision["revisionId"],
            "sha256": revision["contentHash"],
        }

    def status(self, import_id=None):
        origin, current = self._status_selection()
        pending_path = self._pending_path()
        pending = pending_path.exists() or pending_path.is_symlink()
        if import_id is None:
            import_id = (origin or {}).get("importId")
        if import_id is None:
            return {
                "schemaVersion": "1.0.0",
                "operation": "status",
                "status": "recovery-required" if pending else "no-active-import",
                "capabilityLevel": "contiguous-experimental",
                "currentCanonical": current,
                "nextAction": "Reconcile the exact pending selection"
                if pending
                else "Inspect or prepare a standalone timeline export",
                "target": {
                    "provider": self.provider,
                    "videoId": self.workspace.video_id,
                },
            }
        session = self.load(import_id)
        active = bool(origin and origin["importId"] == import_id)
        state = "active-draft" if active else session["state"]
        if pending:
            state = "recovery-required"
        return self._result(
            "status",
            session,
            status=state,
            currentOrigin=origin,
            currentCanonical=current,
            active=active,
        )
