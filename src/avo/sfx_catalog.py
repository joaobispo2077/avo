"""Read-only sound libraries with immutable, project-local descriptive metadata.

Search deliberately reads saved facts only. Scanning is the explicit boundary for
source reads/analysis; neither an indexed sound nor its peak grants listening approval.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import time
import unicodedata
from copy import deepcopy
from pathlib import Path
from threading import Lock

from avo.library.rules import is_link, observation, safe_path
from avo.sfx_contracts import (
    LIBRARY_ID,
    SfxCatalogError,
    _entry_id,
    _hash,
    _revision,
    _validate_entries,
    _validate_facts,
)
from avo.timeline.contracts import (
    content_hash,
    file_fingerprint,
    fingerprint_stage,
    validate_document,
)
from avo.timeline.store import (
    StoreError,
    atomic_write_json,
    timeline_writer,
    write_immutable_json,
)

SCHEMA = "avo.sfx-catalog.schema.json"
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_TREE_NODES = 20000
AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".aiff",
    ".aif",
    ".w64",
    ".caf",
}
SHA = re.compile(r"^[a-f0-9]{64}$")
_VALIDATED_GENERATIONS = {}
_VALIDATED_GENERATIONS_LOCK = Lock()


def _validate(value, schema=SCHEMA):
    try:
        validate_document(value, schema)
    except (ValueError, TypeError, RecursionError) as exc:
        raise SfxCatalogError(f"invalid catalogue document: {str(exc)[:400]}") from exc
    return value


def _read_bytes(path):
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise SfxCatalogError("catalogue metadata exceeds its byte budget")
        return data
    except (OSError, ValueError, RecursionError) as exc:
        raise SfxCatalogError(f"invalid catalogue metadata: {str(exc)[:300]}") from exc


def _decode(data):
    try:
        return json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise SfxCatalogError(f"invalid catalogue metadata: {str(exc)[:300]}") from exc


def _read(path):
    return _decode(_read_bytes(path))


def _cached_generation(key):
    with _VALIDATED_GENERATIONS_LOCK:
        result = _VALIDATED_GENERATIONS.get(key)
    return deepcopy(result) if result is not None else None


def _remember_generation(key, result):
    retained = deepcopy(result)
    with _VALIDATED_GENERATIONS_LOCK:
        _VALIDATED_GENERATIONS[key] = retained
        while len(_VALIDATED_GENERATIONS) > 2:
            del _VALIDATED_GENERATIONS[next(iter(_VALIDATED_GENERATIONS))]


def _expected(expected, actual):
    if expected != actual:
        raise SfxCatalogError(
            "catalogue generation conflict; reload the current generation"
        )


def _actor(actor, reason):
    if not all(
        isinstance(value, str) and 1 <= len(value.strip()) <= 512
        for value in (actor, reason)
    ):
        raise SfxCatalogError("actor and reason are required (1..512 characters)")
    return {"actor": actor.strip(), "reason": reason.strip()}


def _measurement_key(sha, identity):
    return content_hash({"sourceSha256": sha, "analyzer": identity})


def _rights_state(entry):
    rights = entry["rights"]
    if (
        rights["status"] != "unknown"
        and rights["sourceSha256"] != entry["source"]["sha256"]
    ):
        return "stale"
    return rights["status"]


def _token(value):
    return (
        base64.urlsafe_b64encode(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def _untoken(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise SfxCatalogError("invalid continuation cursor")
    try:
        return json.loads(
            base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            )
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise SfxCatalogError("invalid continuation cursor") from exc


def _budget(value):
    result = {"maxFiles": 500, "maxBytes": 256 * 1024 * 1024, "maxSeconds": 60}
    if value is not None:
        if not isinstance(value, dict) or set(value) - set(result):
            raise SfxCatalogError("unknown scan budget")
        result.update(value)
    limits = {"maxFiles": MAX_ENTRIES, "maxBytes": 2 * 1024**3, "maxSeconds": 3600}
    for key, limit in limits.items():
        item = result[key]
        if not _positive(item, limit):
            raise SfxCatalogError(f"invalid scan budget {key}")
    if type(result["maxFiles"]) is not int or type(result["maxBytes"]) is not int:
        raise SfxCatalogError("file and byte budgets require integers")
    return result


def _positive(value, limit):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= limit


def _walk(root):
    """Yield bounded deterministic candidates; links are visible skips, never opened."""
    stack, count = [root], 0
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as stream:
            nodes = []
            for node in stream:
                count += 1
                if count > MAX_TREE_NODES:
                    yield None, "enumeration-budget"
                    return
                nodes.append(node)
        for node in sorted(nodes, key=lambda item: (item.name.casefold(), item.name)):
            path = Path(node.path)
            if is_link(path):
                yield None, "linked-source"
            elif node.is_dir(follow_symlinks=False):
                stack.append(path)
            elif (
                node.is_file(follow_symlinks=False)
                and path.suffix.lower() in AUDIO_EXTENSIONS
            ):
                yield path.relative_to(root).as_posix(), None


def _check_root(root, output):
    from avo.adapters.media.local_source import local_source_arguments

    local_source_arguments(root)
    safe_path(root, ".root-check")
    if not root.is_dir() or is_link(root):
        raise SfxCatalogError("selected sound root is missing or linked")
    resolved, metadata = root.resolve(), output.resolve()
    if metadata.is_relative_to(resolved) or resolved.is_relative_to(metadata):
        raise SfxCatalogError("read-only sound root overlaps catalogue output")


def _inventory(roots, output):
    if not roots:
        raise SfxCatalogError("scan requires at least one declared sound root")
    files, warnings, complete = [], [], True
    for library, root in sorted(roots.items()):
        try:
            _check_root(root, output)
            for relative, issue in _walk(root):
                if issue:
                    warnings.append({"libraryId": library, "kind": issue})
                    complete = complete and issue != "enumeration-budget"
                else:
                    files.append((library, relative))
                if len(files) >= MAX_ENTRIES:
                    complete = False
                    warnings.append({"libraryId": library, "kind": "entry-budget"})
                    return sorted(files), warnings, complete
        except (OSError, ValueError) as exc:
            raise SfxCatalogError(
                f"unsafe sound root {library}: {str(exc)[:300]}"
            ) from exc
    return sorted(files), warnings[:MAX_TREE_NODES], complete


def _new_entry(library, relative):
    return {
        "entryId": _entry_id(library, relative),
        "entryRevision": "0" * 64,
        "libraryId": library,
        "relativePath": relative,
        "source": {"sha256": None, "sizeBytes": 0, "state": "unavailable"},
        "measurement": None,
        "curation": {
            "material": None,
            "tags": [],
            "favorite": False,
            "variantGroup": None,
        },
        "rights": {
            "status": "unknown",
            "license": None,
            "evidenceRef": None,
            "sourceSha256": None,
        },
        "marker": None,
        "annotationRevision": 0,
        "conflicts": [],
    }


class SfxCatalogService:
    """Project-local catalogue; constructing and reading never scan/decode sources."""

    def __init__(self, workspace, *, roots, analyzer=None, semantic=None):
        if (
            not isinstance(roots, dict)
            or len(roots) > 32
            or any(not LIBRARY_ID.fullmatch(key) for key in roots)
        ):
            raise SfxCatalogError("sound roots require at most 32 named library IDs")
        self.workspace = workspace
        self.roots = {
            key: Path(value).expanduser().absolute() for key, value in roots.items()
        }
        self.analyzer = analyzer
        self.semantic = semantic
        self.directory = Path(workspace.raw_dir).absolute() / "edit" / "sfx-catalog"

    def _path(self, relative):
        try:
            return safe_path(
                Path(self.workspace.raw_dir).absolute(), f"edit/sfx-catalog/{relative}"
            )
        except (ValueError, OSError) as exc:
            raise SfxCatalogError(f"unsafe catalogue metadata path: {exc}") from exc

    def _empty(self):
        return {
            "schemaVersion": "1.0.0",
            "generationId": None,
            "parentGenerationId": None,
            "roots": {key: str(path) for key, path in sorted(self.roots.items())},
            "entries": [],
            "operation": {"kind": "empty", "actor": "avo", "reason": "not scanned"},
            "coverage": {
                "complete": False,
                "processed": 0,
                "discovered": 0,
                "skipped": 0,
                "reason": "not-scanned",
            },
            "resume": None,
            "warnings": [],
        }

    def _selector(self):
        path = self._path("current.json")
        if not path.exists():
            return None
        selector = _read(path)
        if (
            not isinstance(selector, dict)
            or set(selector) != {"schemaVersion", "generationId"}
            or selector["schemaVersion"] != "1.0.0"
        ):
            raise SfxCatalogError("invalid catalogue generation selector")
        return selector

    def show(self, generation=None):
        """Read a bounded validated generation, without probing source availability."""
        if generation is None:
            selector = self._selector()
            if selector is None:
                return self._empty()
            generation = selector["generationId"]
        if not isinstance(generation, str) or not SHA.fullmatch(generation):
            raise SfxCatalogError("invalid catalogue generation identity")
        path = self._path(f"generations/{generation}.json").resolve()
        data = _read_bytes(path)
        # Re-read exact bytes across service instances; stat/mtime never confer trust.
        key = (str(path), generation, hashlib.sha256(data).hexdigest())
        cached = _cached_generation(key)
        if cached is not None:
            return cached
        result = _validate(_decode(data))
        if (
            result["generationId"] != generation
            or _hash(result, "generationId") != generation
        ):
            raise SfxCatalogError("catalogue generation hash mismatch")
        _validate_entries(result["entries"])
        _remember_generation(key, result)
        return result

    def _publish(self, result, expected):
        result["parentGenerationId"] = expected
        result["generationId"] = _hash(result, "generationId")
        _validate(result)
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES:
            raise SfxCatalogError("catalogue generation exceeds its byte budget")
        self._path(".mutation.lock")
        try:
            with timeline_writer(self.directory):
                _expected(expected, self.show()["generationId"])
                path = self._path(f"generations/{result['generationId']}.json")
                if path.exists():
                    _read(path)
                write_immutable_json(path, result)
                atomic_write_json(
                    self._path("current.json"),
                    {"schemaVersion": "1.0.0", "generationId": result["generationId"]},
                )
        except StoreError as exc:
            raise SfxCatalogError(
                f"catalogue generation writer conflict: {exc}"
            ) from exc
        return result

    def _analyzer(self):
        if self.analyzer is None:
            from avo.adapters.media.sfx_analysis import SfxAnalyzer

            self.analyzer = SfxAnalyzer()
        identity = getattr(self.analyzer, "identity", None)
        _validate(identity, f"{SCHEMA}#/$defs/analyzer")
        return identity

    def _scan_entry(self, entry, cache, identity, max_bytes):
        path = safe_path(self.roots[entry["libraryId"]], entry["relativePath"])
        before = observation(path)
        if before["sizeBytes"] > max_bytes:
            return None, 0
        with fingerprint_stage():
            fingerprint = file_fingerprint(path)
        if observation(path) != before:
            raise SfxCatalogError("source changed while fingerprinting")
        sha = fingerprint["sha256"]
        key = _measurement_key(sha, identity)
        measurement = cache.get(key)
        if measurement is None:
            measurement = self.analyzer(path, source_sha256=sha)
            _validate(measurement, f"{SCHEMA}#/$defs/measurementFacts")
            _validate_facts(measurement)
            if (
                measurement["sourceSha256"] != sha
                or measurement["analyzer"] != identity
            ):
                raise SfxCatalogError(
                    "analyzer returned a different source/config identity"
                )
            measurement = {
                **measurement,
                "measurementHash": _hash(measurement, "measurementHash"),
            }
            with fingerprint_stage():
                verified = file_fingerprint(path)
            if verified["sha256"] != sha:
                raise SfxCatalogError("source bytes changed while analyzing")
        if observation(path) != before:
            raise SfxCatalogError("source changed while analyzing")
        cache[key] = measurement
        old_sha = entry["source"]["sha256"]
        if old_sha and old_sha != sha:
            entry["conflicts"].append(
                {
                    "kind": "source-changed",
                    "previousSha256": old_sha,
                    "currentSha256": sha,
                    "annotationRevision": entry["annotationRevision"],
                }
            )
        entry["source"] = {
            "sha256": sha,
            "sizeBytes": before["sizeBytes"],
            "state": "available",
        }
        entry["measurement"] = deepcopy(measurement)
        entry["entryRevision"] = _revision(entry)
        return entry, before["sizeBytes"]

    def scan(
        self,
        *,
        expected_generation=None,
        actor,
        reason,
        budget=None,
        cancelled=None,
        progress=None,
        resume=None,
    ):
        """Explicit bounded source work; a competing writer cannot lose manual notes."""
        operation = {"kind": "scan", **_actor(actor, reason)}
        limits = _budget(budget)
        previous = self.show()
        _expected(expected_generation, previous["generationId"])
        if previous["roots"] != self._empty()["roots"]:
            raise SfxCatalogError(
                "declared sound roots differ from the saved generation"
            )
        inventory, warnings, enumerated = _inventory(self.roots, self.directory)
        start, visited = self._resume(previous, resume, inventory)
        entries = {entry["entryId"]: deepcopy(entry) for entry in previous["entries"]}
        identity = self._analyzer()
        cache = _measurement_cache(entries)
        processed, stop = self._scan_population(
            inventory,
            start,
            visited,
            entries,
            cache,
            identity,
            limits,
            cancelled,
            progress,
            warnings,
        )
        cursor = start + processed
        complete = cursor == len(inventory) and enumerated and stop is None
        if complete:
            _mark_missing(entries, visited)
        result = {
            **previous,
            "entries": sorted(
                entries.values(),
                key=lambda item: (item["libraryId"], item["relativePath"]),
            ),
            "operation": operation,
            "warnings": warnings,
            "coverage": {
                "complete": complete,
                "processed": cursor,
                "discovered": len(inventory),
                "skipped": len(warnings),
                "reason": stop or ("complete" if complete else "enumeration-budget"),
            },
            "resume": None,
        }
        if not complete:
            result["resume"] = {
                "inventoryHash": content_hash(inventory),
                "offset": cursor,
                "visitedIds": sorted(visited),
            }
        return self._publish(result, expected_generation)

    def _scan_population(
        self,
        inventory,
        start,
        visited,
        entries,
        cache,
        identity,
        limits,
        cancelled,
        progress,
        warnings,
    ):
        processed, used, stop, began = 0, 0, None, time.monotonic()
        for index in range(start, len(inventory)):
            stop = _stop(limits, processed, used, began, cancelled)
            if stop:
                break
            library, relative = inventory[index]
            entry = entries.get(
                _entry_id(library, relative), _new_entry(library, relative)
            )
            updated, size = self._try_entry(
                entry, cache, identity, limits["maxBytes"] - used, warnings
            )
            if updated is None:
                stop = "byte-budget"
                break
            entries[entry["entryId"]] = updated
            visited.add(entry["entryId"])
            processed, used = processed + 1, used + size
            if progress:
                progress(
                    {
                        "processed": processed,
                        "discovered": len(inventory),
                        "relativePath": relative,
                        "bytes": used,
                    }
                )
        return processed, stop

    def _resume(self, previous, resume, inventory):
        if resume is None:
            return 0, set()
        if not resume or content_hash(resume) != content_hash(previous["resume"]):
            raise SfxCatalogError("scan resume generation changed; restart explicitly")
        if resume["inventoryHash"] != content_hash(inventory):
            raise SfxCatalogError(
                "scan resume population/generation changed; restart explicitly"
            )
        return resume["offset"], set(resume["visitedIds"])

    def _try_entry(self, entry, cache, identity, available, warnings):
        try:
            return self._scan_entry(entry, cache, identity, available)
        except (OSError, ValueError) as exc:
            entry["source"]["state"] = "unavailable"
            entry["entryRevision"] = _revision(entry)
            warnings.append(
                {
                    "libraryId": entry["libraryId"],
                    "kind": "analysis-unavailable",
                    "detail": str(exc)[:512],
                }
            )
            return entry, 0

    def annotate(self, entry_id, patch, *, expected_generation, actor, reason):
        """Revision curation without turning measured peaks into human approval."""
        operation = {"kind": "annotate", **_actor(actor, reason)}
        _validate(patch, f"{SCHEMA}#/$defs/annotationPatch")
        result = self.show()
        _expected(expected_generation, result["generationId"])
        entry = next(
            (item for item in result["entries"] if item["entryId"] == entry_id), None
        )
        if entry is None:
            raise SfxCatalogError("unknown catalogue entry")
        _apply_patch(entry, patch)
        result["operation"] = operation
        return self._publish(result, expected_generation)

    def search(
        self,
        query,
        *,
        filters=None,
        limit=20,
        cursor=None,
        generation=None,
        mode="descriptor",
    ):
        """Transparent bounded metadata ranking. Semantic never silently falls back."""
        request = _search_request(query, filters, limit, mode)
        document = self.show(generation)
        basis = {**request, "generationId": document["generationId"]}
        counts = _counts(document)
        result = {
            "schemaVersion": "1.0.0",
            "status": "no-match",
            "mode": mode,
            "scoreMeaning": "matched query token fraction; curated and filename descriptors only",
            "generationId": document["generationId"],
            "query": query,
            "filters": request["filters"],
            "results": [],
            "counts": counts,
            "nextCursor": None,
            "warnings": []
            if document["coverage"]["complete"]
            else ["Catalogue scan coverage is partial or unavailable."],
        }
        if mode == "semantic":
            ranked, disclosure, warnings = _semantic_rank(
                self.semantic, document, query, request["filters"]
            )
            if disclosure is None:
                return _validate(
                    {
                        **result,
                        "status": "unavailable",
                        "scoreMeaning": "unavailable: no provisioned local joint encoder",
                        "warnings": warnings,
                    },
                    "avo.sfx-search.schema.json",
                )
            result.update(
                jointSpace=disclosure,
                scoreMeaning="cosine similarity in the disclosed local joint audio/text space",
            )
            result["warnings"] = (result["warnings"] + warnings)[:64]
            result["counts"]["indexed"] = len(ranked)
            basis["jointSpace"] = disclosure
        else:
            ranked = _rank(document["entries"], query, request["filters"])
        offset = _cursor_offset(cursor, basis)
        result["results"] = ranked[offset : offset + limit]
        result["status"] = "ok" if result["results"] else "no-match"
        if offset + limit < len(ranked):
            result["nextCursor"] = _token(
                {"basis": content_hash(basis), "offset": offset + limit}
            )
        return _validate(result, "avo.sfx-search.schema.json")


def _stop(limits, processed, used, began, cancelled):
    if cancelled and cancelled():
        return "cancelled"
    if processed >= limits["maxFiles"]:
        return "file-budget"
    if used >= limits["maxBytes"]:
        return "byte-budget"
    if time.monotonic() - began >= limits["maxSeconds"]:
        return "time-budget"
    return None


def _apply_patch(entry, patch):
    sha = entry["source"]["sha256"]
    for key in ("curation", "rights"):
        if key in patch:
            entry[key].update(deepcopy(patch[key]))
    if "rights" in patch:
        entry["rights"]["sourceSha256"] = sha
        _check_rights(entry["rights"])
    if "marker" in patch:
        marker, measurement = patch["marker"], entry["measurement"]
        _check_marker(marker, measurement)
        entry["marker"] = {**marker, "sourceSha256": sha} if marker else None
    entry["annotationRevision"] += 1


def _check_rights(rights):
    if rights["status"] == "licensed" and not all(
        rights[key] for key in ("license", "evidenceRef")
    ):
        raise SfxCatalogError(
            "licensed rights require declared license and evidence reference"
        )


def _check_marker(marker, measurement):
    if marker and (
        not measurement or marker["sample"] >= measurement["analyzedSamples"]
    ):
        raise SfxCatalogError("marker must lie in the actually analyzed source range")


def _mark_missing(entries, visited):
    for entry in entries.values():
        if entry["entryId"] not in visited:
            entry["source"]["state"] = "missing"


def _measurement_cache(entries):
    return {
        _measurement_key(item["sourceSha256"], item["analyzer"]): item
        for entry in entries.values()
        if (item := entry["measurement"])
    }


def _search_request(query, filters, limit, mode):
    if not isinstance(query, str) or not query.strip() or not 1 <= len(query) <= 512:
        raise SfxCatalogError("query length must be 1..512 characters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise SfxCatalogError("search limit must be 1..100")
    if mode not in {"descriptor", "semantic"}:
        raise SfxCatalogError("unknown matching mode")
    filters = {} if filters is None else filters
    _validate(filters, "avo.sfx-search.schema.json#/$defs/filters")
    return {"query": query, "filters": deepcopy(filters), "limit": limit, "mode": mode}


def _cursor_offset(cursor, basis):
    if cursor is None:
        return 0
    decoded = _untoken(cursor)
    if not isinstance(decoded, dict) or set(decoded) != {"basis", "offset"}:
        raise SfxCatalogError("invalid continuation cursor")
    if (
        decoded["basis"] != content_hash(basis)
        or type(decoded["offset"]) is not int
        or not 0 <= decoded["offset"] <= MAX_ENTRIES
    ):
        raise SfxCatalogError(
            "cursor query/filter/mode/generation differs; restart search"
        )
    return decoded["offset"]


def _words(text):
    return set(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def _counts(document):
    entries = document["entries"]
    return {
        "indexed": sum(item["measurement"] is not None for item in entries),
        "unknownRights": sum(_rights_state(item) == "unknown" for item in entries),
        "unavailable": sum(item["source"]["state"] != "available" for item in entries),
        "partialAnalysis": sum(
            (item["measurement"] or {}).get("coverage") == "partial" for item in entries
        ),
    }


def _eligible(entry, filters):
    measured = entry["measurement"]
    if entry["source"]["state"] != "available" or not measured or measured["silence"]:
        return False
    checks = [
        not filters.get("libraryIds") or entry["libraryId"] in filters["libraryIds"],
        not filters.get("rights") or _rights_state(entry) in filters["rights"],
        "favorite" not in filters
        or entry["curation"]["favorite"] == filters["favorite"],
        not filters.get("material")
        or entry["curation"]["material"] == filters["material"],
        set(filters.get("tags", [])).issubset(entry["curation"]["tags"]),
    ]
    return all(checks) and _feature_filters(measured, filters)


def _feature_filters(measured, filters):
    for key, field, lower in (
        ("minDurationSeconds", "durationSeconds", True),
        ("maxDurationSeconds", "durationSeconds", False),
        ("minCentroidHz", "spectralCentroidHz", True),
        ("maxCentroidHz", "spectralCentroidHz", False),
        ("maxAttackSeconds", "attackSeconds", False),
    ):
        if key in filters and (
            measured[field] is None
            or (
                measured[field] < filters[key]
                if lower
                else measured[field] > filters[key]
            )
        ):
            return False
    return True


def _rank(entries, query, filters):
    tokens, ranked = _words(query), []
    for entry in entries:
        if not _eligible(entry, filters):
            continue
        curated = entry["curation"]
        descriptors = " ".join(
            [entry["relativePath"], curated["material"] or "", *curated["tags"]]
        )
        matched = sorted(tokens & _words(descriptors))
        if not tokens or len(matched) / len(tokens) < 0.5:
            continue
        ranked.append(
            _result_row(
                entry,
                len(matched) / len(tokens),
                [f"descriptor token: {word}" for word in matched],
            )
        )
    return _ordered(ranked)


def _result_row(entry, score, reasons):
    measured = entry["measurement"]
    return {
        "entryId": entry["entryId"],
        "entryRevision": entry["entryRevision"],
        "libraryId": entry["libraryId"],
        "relativePath": entry["relativePath"],
        "sourceSha256": entry["source"]["sha256"],
        "sourceState": entry["source"]["state"],
        "rightsState": _rights_state(entry),
        "rights": entry["rights"],
        "curation": entry["curation"],
        "marker": entry["marker"],
        "score": score,
        "reasons": reasons,
        "usefulDurationSeconds": (
            measured["usefulRange"]["endSampleExclusive"]
            - measured["usefulRange"]["startSample"]
        )
        / measured["sampleRate"],
        "level": {"rms": measured["rms"], "peak": measured["peak"]},
        "anchorCandidates": measured["onsets"],
        "analysisCoverage": measured["coverage"],
        "audition": {
            "libraryId": entry["libraryId"],
            "relativePath": entry["relativePath"],
            "sourceSha256": entry["source"]["sha256"],
            "sampleRate": measured["sampleRate"],
            **measured["usefulRange"],
        },
    }


def _ordered(ranked):
    return sorted(
        ranked,
        key=lambda item: (
            -item["score"],
            item["libraryId"],
            item["relativePath"].casefold(),
            item["relativePath"],
            item["entryId"],
        ),
    )


def _semantic_rank(backend, document, query, filters):
    if backend is None:
        return (
            [],
            None,
            [
                "Select descriptor mode explicitly, or provision the optional semantic capability."
            ],
        )
    eligible = {
        item["entryId"]: item
        for item in document["entries"]
        if _eligible(item, filters)
    }
    ranking = backend.rank(document, {"query": query, "entryIds": list(eligible)})
    _validate(ranking, "avo.sfx-search.schema.json#/$defs/semanticRanking")
    if ranking["status"] == "unavailable":
        return [], None, ranking["warnings"]
    rows, seen = [], set()
    for score in ranking["scores"]:
        entry = eligible.get(score["entryId"])
        if (
            entry is None
            or score["entryId"] in seen
            or entry["entryRevision"] != score["entryRevision"]
        ):
            raise SfxCatalogError(
                "semantic score has unknown, duplicate or stale entry revision"
            )
        seen.add(score["entryId"])
        rows.append(
            _result_row(
                entry,
                score["score"],
                ["local joint-space cosine similarity; audition required"],
            )
        )
    warnings = ranking["warnings"]
    if len(seen) < len(eligible):
        warnings = [
            *warnings,
            f"Semantic vectors unavailable for {len(eligible) - len(seen)} eligible entries.",
        ]
    return _ordered(rows), ranking["jointSpace"], warnings
