"""Bounded filename-only relink evidence within explicitly declared local roots."""

from __future__ import annotations

import math
import os
import re
import stat
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .contracts import (
    ContractError,
    canonical_json_bytes,
    file_fingerprint,
    fingerprint_stage,
)
from .otio_import import ImportError

MAX_SCAN_ENTRIES = 10_000
MAX_CANDIDATES = 64
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


def _finding(error):
    return {
        "code": error.code,
        "scope": error.scope,
        "message": str(error)[:512],
        "blocking": True,
        "evidenceOrigin": "capability-check",
        "remediation": "Narrow the declared local media roots or explicitly select and confirm an original file mapping.",
    }


def _spend(report, value):
    size = len(canonical_json_bytes(value)) + 2
    if size > report["remaining"]:
        report["limited"] = True
        return False
    report["remaining"] -= size
    return True


def _add_finding(report, error):
    finding = _finding(error)
    if _spend(report, finding):
        report["findings"].append(finding)


def _target_basename(value):
    if not isinstance(value, str):
        return None
    if not re.match(r"^[a-zA-Z]:[\\/]", value):
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if parsed.scheme:
            if parsed.scheme.lower() != "file" or parsed.netloc.lower() not in {
                "",
                "localhost",
            }:
                return None
            value = unquote(parsed.path)
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def _basename(reference):
    name = (
        reference["basename"]
        if "basename" in reference
        else _target_basename(reference.get("targetUrl"))
    )
    if (
        not isinstance(name, str)
        or name in {"", ".", ".."}
        or any(char in name for char in ("/", "\\", "\x00"))
    ):
        return None
    return name.casefold()


def _references(references, report):
    names = {}
    for reference in references:
        if reference.get("active") is not True:
            continue
        pointer = reference["pointer"]
        if pointer not in report["mappings"]:
            mapping = {"status": "unresolved", "candidates": []}
            if not _spend(report, {pointer: mapping}):
                break
            report["mappings"][pointer] = mapping
        name = _basename(reference)
        if name is not None:
            pointers = names.setdefault(name, [])
            if pointer not in pointers:
                pointers.append(pointer)
    return names


def _local_absolute(value):
    text = str(value)
    if text.startswith(("\\\\", "//")) or "://" in text or "\x00" in text:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Media roots must be explicit local absolute directories",
        )
    path = Path(value)
    if not path.is_absolute():
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Media roots must be explicit local absolute directories",
        )
    return path


def _reparse(metadata):
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def _contained(path, roots, prohibited):
    return any(path.is_relative_to(root) for root in roots) and not any(
        path.is_relative_to(root) for root in prohibited
    )


def _roots(roots, prohibited, report, counter):
    allowed = []
    for value in roots:
        try:
            _ensure_scan_room(counter)
            counter[0] += 1
            path = _local_absolute(value)
            metadata = path.lstat()
            if _reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise ImportError(
                    "OTIO_SOURCE_PROHIBITED",
                    "Media root is not an ordinary local directory",
                )
            path = path.resolve(strict=True)
            if any(path.is_relative_to(root) for root in prohibited):
                raise ImportError(
                    "OTIO_SOURCE_PROHIBITED",
                    "Media root is inside prohibited source storage",
                )
            if path not in allowed:
                allowed.append(path)
        except ImportError as error:
            _add_finding(report, error)
            if error.code == "OTIO_INPUT_LIMIT":
                break
        except (OSError, ValueError):
            _add_finding(
                report,
                ImportError("OTIO_MEDIA_MISSING", "Declared media root is unavailable"),
            )
    return allowed


def _ensure_scan_room(counter):
    if counter[0] >= MAX_SCAN_ENTRIES:
        raise ImportError(
            "OTIO_INPUT_LIMIT",
            "Media discovery reached its bounded directory/entry scan limit",
        )


def _scan_entries(directory, counter):
    _ensure_scan_room(counter)
    with os.scandir(directory) as entries:
        while True:
            _ensure_scan_room(counter)
            try:
                entry = next(entries)
            except StopIteration:
                return
            counter[0] += 1
            yield entry


def _scan_entry(entry, roots, prohibited):
    metadata = entry.stat(follow_symlinks=False)
    if _reparse(metadata):
        return None
    path = Path(entry.path).resolve(strict=True)
    if not _contained(path, roots, prohibited):
        return None
    if not stat.S_ISDIR(metadata.st_mode) and not stat.S_ISREG(metadata.st_mode):
        return None
    return path, stat.S_ISDIR(metadata.st_mode)


def _scan_files(roots, prohibited, counter):
    pending, visited = list(reversed(roots)), set()
    while pending:
        directory = pending.pop()
        if directory in visited:
            continue
        visited.add(directory)
        try:
            if not _contained(
                directory.resolve(strict=True), roots, prohibited
            ) or _reparse(directory.lstat()):
                continue
            for entry in _scan_entries(directory, counter):
                candidate = _scan_entry(entry, roots, prohibited)
                if candidate is None:
                    continue
                path, directory_entry = candidate
                if directory_entry:
                    pending.append(path)
                else:
                    yield path
        except OSError:
            yield ImportError(
                "OTIO_RUNTIME_UNAVAILABLE",
                "A declared media directory could not be fully inspected",
            )


def _candidate_paths(names, roots, prohibited, report, counter):
    found = {name: set() for name in names}
    capped = set()
    try:
        for path in _scan_files(roots, prohibited, counter):
            if isinstance(path, ImportError):
                _add_finding(report, path)
                continue
            name = path.name.casefold()
            if name not in found or path in found[name]:
                continue
            if len(found[name]) >= MAX_CANDIDATES:
                capped.add(name)
            else:
                found[name].add(path)
    except ImportError as error:
        _add_finding(report, error)
    for name in capped:
        for pointer in names[name]:
            _add_finding(
                report,
                ImportError(
                    "OTIO_INPUT_LIMIT",
                    "Media candidates exceed the per-reference limit",
                    scope=pointer,
                ),
            )
    return found


def _current_file(path, roots, prohibited):
    try:
        if (
            _reparse(path.lstat())
            or path.resolve(strict=True) != path
            or not _contained(path, roots, prohibited)
        ):
            raise ImportError(
                "OTIO_SOURCE_PROHIBITED",
                "Candidate no longer names an authorized ordinary original file",
            )
        with fingerprint_stage():
            return file_fingerprint(path)
    except OSError as exc:
        raise ImportError(
            "OTIO_SOURCE_CHANGED", "Candidate original changed or became unavailable"
        ) from exc


def _probe_description(result, path):
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("sources"), list)
        or len(result["sources"]) != 1
    ):
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Media probe did not return exactly the requested candidate",
        )
    source = result["sources"][0]
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("locator"), str)
        or Path(source["locator"]) != path
    ):
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Media probe candidate locator does not match the requested original",
        )
    fingerprint = source.get("fingerprint")
    if (
        not isinstance(fingerprint, dict)
        or not re.fullmatch(r"[a-f0-9]{64}", str(fingerprint.get("sha256", "")))
        or type(fingerprint.get("sizeBytes")) is not int
    ):
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Media probe returned an invalid candidate fingerprint",
        )
    return source


def _valid_duration(duration):
    if duration is None:
        return True
    if type(duration) not in {int, float}:
        return False
    try:
        return math.isfinite(duration) and duration >= 0
    except OverflowError:
        return False


def _valid_streams(streams):
    return isinstance(streams, dict) and all(
        isinstance(streams.get(kind), list)
        and all(isinstance(item, dict) for item in streams[kind])
        for kind in ("video", "audio")
    )


def _properties(source):
    duration, streams = source.get("durationSeconds"), source.get("streams")
    if not _valid_duration(duration):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Media probe returned an invalid candidate duration"
        )
    if not _valid_streams(streams):
        raise ImportError(
            "OTIO_INPUT_INVALID", "Media probe returned invalid candidate streams"
        )
    properties = {"durationSeconds": duration, "streams": streams}
    try:
        encoded = canonical_json_bytes(properties)
    except ContractError as exc:
        raise ImportError(
            "OTIO_INPUT_INVALID", "Media properties are not finite JSON evidence"
        ) from exc
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ImportError(
            "OTIO_INPUT_LIMIT", "Candidate media properties exceed the report limit"
        )
    return properties


def _probe_candidate(path, roots, prohibited, probe):
    before = _current_file(path, roots, prohibited)
    try:
        result = probe([path])
    except Exception as exc:
        raise ImportError(
            "OTIO_RUNTIME_UNAVAILABLE",
            "Original-media probe could not inspect this candidate",
        ) from exc
    after = _current_file(path, roots, prohibited)
    source = _probe_description(result, path)
    if any(
        before[key] != after[key] or source["fingerprint"][key] != after[key]
        for key in ("sha256", "sizeBytes")
    ):
        raise ImportError(
            "OTIO_SOURCE_CHANGED",
            "Candidate bytes do not match their media probe fingerprint",
        )
    return {
        "path": str(path),
        "fingerprint": {
            "path": str(path),
            "sha256": after["sha256"],
            "sizeBytes": after["sizeBytes"],
        },
        "properties": _properties(source),
        "matchBasis": "filename-only",
    }


def _inspect_candidates(names, paths, roots, prohibited, probe, report):
    cache = {}
    for name, candidates in paths.items():
        for path in sorted(candidates):
            if report["limited"]:
                return
            if path not in cache:
                try:
                    cache[path] = _probe_candidate(path, roots, prohibited, probe)
                except ImportError as error:
                    cache[path] = error
            for pointer in names[name]:
                candidate = cache[path]
                if isinstance(candidate, ImportError):
                    _add_finding(
                        report,
                        ImportError(candidate.code, str(candidate), scope=pointer),
                    )
                elif _spend(report, candidate):
                    report["mappings"][pointer]["candidates"].append(
                        deepcopy(candidate)
                    )


def _complete_report(report):
    for pointer, mapping in report["mappings"].items():
        count = len(mapping["candidates"])
        mapping["status"] = "ambiguous" if count > 1 else "unresolved"
        code = "OTIO_MEDIA_AMBIGUOUS" if count else "OTIO_MEDIA_MISSING"
        message = (
            "Filename-only candidates require explicit original identity confirmation"
            if count
            else "No verified filename-only candidate was found in the declared roots"
        )
        _add_finding(report, ImportError(code, message, scope=pointer))
    limit = _finding(
        ImportError(
            "OTIO_INPUT_LIMIT", "Candidate discovery reached its global output limit"
        )
    )
    if report["limited"]:
        report["findings"].append(limit)
    result = {"mediaMappings": report["mappings"], "findings": report["findings"]}
    if len(canonical_json_bytes(result)) > MAX_OUTPUT_BYTES:
        return {}, [limit]
    return report["mappings"], report["findings"]


def discover_candidates(references, roots, *, probe, prohibited_roots=()):
    """Return bounded suggestions, never selected sources or admission authority."""
    report = {
        "mappings": {},
        "findings": [],
        "limited": False,
        "remaining": MAX_OUTPUT_BYTES - 1152,
    }
    names = _references(references, report)
    if names:
        try:
            prohibited = [
                _local_absolute(value).resolve() for value in prohibited_roots
            ]
            counter = [0]
            allowed = _roots(roots, prohibited, report, counter)
            paths = _candidate_paths(names, allowed, prohibited, report, counter)
            _inspect_candidates(names, paths, allowed, prohibited, probe, report)
        except ImportError as error:
            _add_finding(report, error)
    return _complete_report(report)
