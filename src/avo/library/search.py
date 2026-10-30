"""Rebuildable local search; canonical library records remain authoritative."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import sqlite3
import stat
import unicodedata
from datetime import date

from avo.library.rules import (
    LibraryError,
    _component,
    _relative_parts,
    finite_seconds,
    no_constant,
    reject,
)
from avo.timeline.contracts import content_hash
from avo.transcribe import resolve_language, validate_transcript_payload

MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024
MAX_TRANSCRIPT_WORDS = 100_000
FILTERS = {
    "group",
    "dateFrom",
    "dateTo",
    "minDuration",
    "maxDuration",
    "transcriptStatus",
}


def _fold(value):
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _options(query, mode, limit, filters):
    if not isinstance(query, str) or not 1 <= len(query) <= 512 or not query.strip():
        reject("LIB_INVALID_REQUEST", "Search query must contain 1 to 512 characters")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or mode not in ("all", "metadata", "speech")
    ):
        reject(
            "LIB_INVALID_REQUEST",
            "Choose a supported search mode and limit from 1 to 100",
        )
    return _fold(query.strip()), _filter_options({} if filters is None else filters)


def _filter_options(filters):
    if not isinstance(filters, dict) or set(filters) - FILTERS:
        reject("LIB_INVALID_REQUEST", "Unknown search filter")
    for key in ("minDuration", "maxDuration"):
        if key in filters and not finite_seconds(filters[key]):
            reject(
                "LIB_INVALID_REQUEST",
                "Duration filters must be finite nonnegative seconds",
            )
    _filter_dates(filters)
    _filter_ranges(filters)
    if "transcriptStatus" in filters and filters["transcriptStatus"] not in (
        "ready",
        "missing",
        "stale",
        "failed",
    ):
        reject("LIB_INVALID_REQUEST", "Unknown transcript status")
    _group_filter(filters)
    return filters


def _group_filter(filters):
    if "group" in filters and (
        not isinstance(filters["group"], str) or not filters["group"]
    ):
        reject("LIB_INVALID_REQUEST", "Group filter requires an ID")


def _filter_dates(filters):
    for key in ("dateFrom", "dateTo"):
        if key in filters:
            try:
                date.fromisoformat(filters[key])
            except (ValueError, TypeError):
                reject("LIB_INVALID_REQUEST", "Date filters require YYYY-MM-DD")


def _filter_ranges(filters):
    if filters.get("minDuration", 0) > filters.get("maxDuration", float("inf")):
        reject("LIB_INVALID_REQUEST", "Duration filter range is reversed")
    if filters.get("dateFrom", "") > filters.get("dateTo", "9999-12-31"):
        reject("LIB_INVALID_REQUEST", "Date filter range is reversed")


def _regular_stat(info):
    return (
        stat.S_ISREG(info.st_mode)
        and not getattr(info, "st_file_attributes", 0) & 0x400
    )


def _observed(service, relative, checked_parents):
    try:
        parts = _relative_parts(relative)
        parent = service.root
        for part in parts:
            _component(part)
        for part in parts[:-1]:
            parent = parent / part
            if parent not in checked_parents:
                info = parent.lstat()
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400
                ):
                    return None
                checked_parents.add(parent)
        info = (parent / parts[-1]).lstat()
        if not _regular_stat(info):
            return None
        return {
            "sizeBytes": info.st_size,
            "mtimeNs": info.st_mtime_ns,
            "ctimeNs": info.st_ctime_ns,
            "device": info.st_dev,
            "fileId": info.st_ino,
        }
    except (OSError, LibraryError, TypeError):
        return None


def _snapshot(service, *, observe=True):
    # Validate the root/ancestors afresh; parent memoization lasts this call only.
    service.store.path("edit/library-index.json")
    head = service.store.head()
    if not head["inventoryRef"]:
        reject(
            "LIB_CACHE_UNAVAILABLE", "Scan the library before searching", "unavailable"
        )
    inventory = service.store.get(head["inventoryRef"])
    if len(inventory["recordings"]) > 10_000:
        reject("LIB_INPUT_TOO_LARGE", "Search inventory exceeds 10,000 recordings")
    proposal = (
        service.store.get(head["proposalRef"])
        if head["proposalRef"]
        else {"groups": [], "actions": []}
    )
    groups = {group["id"]: group["label"] for group in proposal["groups"]}
    assignments = {
        action["recordingId"]: action["groupId"] for action in proposal["actions"]
    }
    states = [
        {
            "recording": recording,
            "source": None,
            "output": None,
            "group": assignments.get(recording["id"]),
            "groupLabel": groups.get(assignments.get(recording["id"]), ""),
        }
        for recording in inventory["recordings"]
    ]
    if observe:
        _observe_states(service, states)
    generation = _generation(head, service.root)
    stamp = content_hash({"generation": generation, "projectionVersion": 3})
    return head, states, generation, stamp


def _observe_state(service, state, checked_parents):
    recording = state["recording"]
    transcript = recording.get("transcript")
    state["source"] = _observed(service, recording["path"], checked_parents)
    state["output"] = (
        _observed(service, transcript.get("path"), checked_parents)
        if isinstance(transcript, dict)
        else None
    )
    return state


def _observe_states(service, states):
    checked_parents = {service.root}
    for state in states:
        _observe_state(service, state, checked_parents)


def _generation(head, root):
    return content_hash(
        {
            "library": head["libraryId"],
            "root": str(root),
            "inventory": head["inventoryRef"]["sha256"]
            if head["inventoryRef"]
            else None,
            "proposal": head["proposalRef"]["sha256"] if head["proposalRef"] else None,
        }
    )


def generation_for(service):
    """Bind handoffs to the current canonical inventory and proposal only."""
    return _generation(service.store.head(), service.root)


def _read_transcript(service, ref):
    path = service.store.path(ref["path"])
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if size > MAX_TRANSCRIPT_BYTES:
            raise ValueError("Transcript output exceeds its byte limit")
        raw = stream.read(size + 1)
    if len(raw) != size:
        raise ValueError("Transcript output size changed while reading")
    if (
        len(raw) > MAX_TRANSCRIPT_BYTES
        or hashlib.sha256(raw).hexdigest() != ref["sha256"]
    ):
        raise ValueError("Transcript output differs from admitted bytes")
    payload = json.loads(raw, parse_constant=no_constant)
    words = payload["words"]
    if not isinstance(words, list) or len(words) > MAX_TRANSCRIPT_WORDS:
        raise ValueError("Transcript word count exceeds its limit")
    validate_transcript_payload(payload)
    return payload


def _transcript_configuration(payload, ref):
    if (
        payload["source"]["sha256"] != ref["sourceSha256"]
        or payload["model"] != ref["model"]
    ):
        raise ValueError("Transcript source or model differs")
    requested = ref["requestedLanguage"]
    if (
        requested != "auto"
        and payload["language_code"] != resolve_language(requested)[1]
    ):
        raise ValueError("Transcript language differs")
    for key in ("engine", "engine_version"):
        if key in ref and payload[key] != ref[key]:
            raise ValueError("Transcript engine configuration differs")


def _transcript_times(words, duration):
    for word in words:
        if not finite_seconds(word["start"]) or not finite_seconds(word["end"]):
            raise ValueError("Transcript timestamps are invalid")
        if duration is not None and word["end"] > duration:
            raise ValueError("Transcript extends past the recording duration")


def _transcript(service, state):
    recording = state["recording"]
    ref = recording.get("transcript")
    if not ref:
        return "missing", None
    if not isinstance(ref, dict):
        return "failed", None
    if (
        state["source"] != recording["observation"]
        or state["source"] != ref.get("observation")
        or recording["availability"] != "available"
    ):
        return "stale", None
    try:
        if not state["output"] or state["output"]["sizeBytes"] > MAX_TRANSCRIPT_BYTES:
            return "failed", None
        payload = _read_transcript(service, ref)
        _transcript_configuration(payload, ref)
        _transcript_times(
            payload["words"], recording["metadata"].get("durationSeconds")
        )
        return "ready", payload
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return "failed", None


def _phrases(words):
    current = []
    for index, word in enumerate(words):
        if current and (
            word["start"] - current[-1][1]["end"] >= 0.5 or len(current) >= 40
        ):
            yield current
            current = []
        current.append((index, word))
    if current:
        yield current


def _document(
    recording, state, generation, kind, text, start=None, end=None, evidence=None
):
    identity = {
        "recordingId": recording["id"],
        "version": recording["version"],
        "generation": generation,
        "matchType": kind,
        "start": start,
        "end": end,
        "evidence": evidence,
    }
    fresh = state["source"] == recording["observation"]
    return {
        **identity,
        "id": content_hash(identity),
        "path": recording["path"],
        "availability": recording["availability"],
        "metadataFreshness": "observed" if fresh else "stale",
        "metadataOnly": kind == "metadata",
        "text": text,
        "score": 1,
    }


def _projection_rows(service, head, states, generation):
    coverage = {
        "totalRecordings": len(states),
        "speechSearchable": 0,
        "unsearchedSpeech": 0,
        "invalidTranscripts": 0,
        "staleTranscripts": 0,
    }
    rows = []
    for completed, state in enumerate(states):
        recording = state["recording"]
        if completed % 100 == 0:
            service.activity(
                completed, len(states), recording["path"], phase="building-search"
            )
        status, payload = _transcript(service, state)
        state["transcriptStatus"] = status
        coverage["speechSearchable"] += status == "ready"
        coverage["invalidTranscripts"] += status == "failed"
        coverage["staleTranscripts"] += status == "stale"
        metadata = _document(
            recording,
            state,
            generation,
            "metadata",
            f"{recording['path']} {state['groupLabel']}",
            evidence={
                "inventoryRef": head["inventoryRef"],
                "recordingVersion": recording["version"],
            },
        )
        metadata["transcriptStatus"] = status
        metadata["indexedStatus"] = status
        metadata["indexedOutputObservation"] = state["output"]
        rows.append((metadata, state, status))
        if payload is None:
            continue
        for phrase in _phrases(payload["words"]):
            start, end = phrase[0][1]["start"], phrase[-1][1]["end"]
            if start >= end:
                continue
            evidence = {
                **recording["transcript"],
                "wordStart": phrase[0][0],
                "wordEnd": phrase[-1][0] + 1,
            }
            document = _document(
                recording,
                state,
                generation,
                "speech",
                " ".join(word["text"] for _, word in phrase),
                start,
                end,
                evidence,
            )
            document["indexedStatus"] = status
            document["indexedOutputObservation"] = state["output"]
            rows.append((document, state, status))
    coverage["unsearchedSpeech"] = len(states) - coverage["speechSearchable"]
    service.activity(
        len(states),
        len(states),
        states[-1]["recording"]["path"] if states else None,
        phase="building-search",
    )
    return rows, coverage


def _network_storage(root):
    if str(root).startswith(("\\\\", "//")):
        return True
    return (
        os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(str(root.anchor)) == 4
    )


def _supports_fts(connection):
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE temp.fts_probe USING fts5(text, tokenize='trigram')"
        )
        connection.execute("DROP TABLE temp.fts_probe")
        return True
    except sqlite3.Error:
        return False


def _connect(service, limitations):
    closed = any(
        service.store.path(f"edit/cleanup/{name}").exists()
        for name in ("cleanup-result.json", "preservation-result.json")
    )
    network = _network_storage(service.root)
    if closed or network:
        limitations.append("closed-project" if closed else "network-storage")
        return sqlite3.connect(":memory:"), False
    try:
        path = service.store.path("edit/library/cache/search.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=0.1)
        connection.execute("PRAGMA journal_mode=DELETE")
        return connection, True
    except (sqlite3.Error, OSError, LibraryError) as exc:
        if "connection" in locals():
            connection.close()
        if getattr(exc, "sqlite_errorcode", None) in {
            sqlite3.SQLITE_NOTADB,
            sqlite3.SQLITE_CORRUPT,
        }:
            limitations.append("cache-rebuilt")
            path.unlink(missing_ok=True)
            return sqlite3.connect(path, timeout=0.1), True
        limitations.append("cache-unavailable")
        return sqlite3.connect(":memory:"), False


def _rebuild(connection, service, head, states, generation, stamp, fts):
    rows, coverage = _projection_rows(service, head, states, generation)
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE IF EXISTS search_fts")
        connection.execute("DROP TABLE IF EXISTS documents")
        connection.execute("DROP TABLE IF EXISTS metadata")
        connection.execute(
            "CREATE TABLE metadata(stamp TEXT,coverage TEXT,fts INTEGER)"
        )
        connection.execute(
            "CREATE TABLE documents(recordingId TEXT,start REAL,kind TEXT,folded TEXT,body TEXT,groupId TEXT,duration REAL,recordingDate TEXT,transcriptStatus TEXT)"
        )
        if fts:
            connection.execute(
                "CREATE VIRTUAL TABLE search_fts USING fts5(folded, tokenize='trigram')"
            )
        for document, state, status in rows:
            metadata = state["recording"]["metadata"]
            folded = _fold(document["text"])
            result = connection.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    document["recordingId"],
                    document["start"],
                    document["matchType"],
                    folded,
                    json.dumps(document, ensure_ascii=False),
                    state["group"],
                    metadata.get("durationSeconds"),
                    metadata.get("recordingDate"),
                    status,
                ),
            )
            if fts:
                connection.execute(
                    "INSERT INTO search_fts(rowid,folded) VALUES(?,?)",
                    (result.lastrowid, folded),
                )
        connection.execute(
            "INSERT INTO metadata VALUES(?,?,?)",
            (stamp, json.dumps(coverage), int(fts)),
        )
    return coverage


def _cache(service, head, states, generation, stamp):
    limitations = []
    connection, persisted = _connect(service, limitations)
    fts = _supports_fts(connection)
    if not fts:
        limitations.append("fts5-unavailable")
    try:
        saved = connection.execute("SELECT stamp,coverage,fts FROM metadata").fetchone()
        if saved and saved[0] == stamp and bool(saved[2]) == fts:
            return connection, json.loads(saved[1]), fts, limitations, persisted
    except (sqlite3.Error, ValueError, TypeError):
        pass
    _observe_states(service, states)
    try:
        coverage = _rebuild(connection, service, head, states, generation, stamp, fts)
    except sqlite3.Error:
        connection.close()
        limitations.append("cache-rebuilt")
        connection = sqlite3.connect(":memory:")
        persisted = False
        coverage = _rebuild(connection, service, head, states, generation, stamp, fts)
    return connection, coverage, fts, limitations, persisted


def _filter_sql(filters):
    clauses, values = [], []
    for key, column, operator in (
        ("group", "groupId", "="),
        ("dateFrom", "recordingDate", ">="),
        ("dateTo", "recordingDate", "<="),
        ("minDuration", "duration", ">="),
        ("maxDuration", "duration", "<="),
        ("transcriptStatus", "transcriptStatus", "="),
    ):
        if key in filters:
            clauses.append(f"{column} {operator} ?")
            values.append(filters[key])
    return clauses, values


def _offset(cursor, context):
    if cursor is None:
        return 0
    try:
        if not isinstance(cursor, str) or len(cursor) > 4096:
            raise ValueError
        document = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if (
            document["context"] != context
            or type(document["offset"]) is not int
            or not 0 <= document["offset"] <= 10_000_000
        ):
            raise ValueError
        return document["offset"]
    except (ValueError, TypeError, KeyError, UnicodeError):
        reject(
            "LIB_STALE_PROPOSAL",
            "Search cursor is invalid or stale; restart the search",
            "stale",
        )


def _excerpt(text, query):
    found = _fold(text).find(query)
    start = max(0, found - 70)
    return text[start : start + 240]


def _matches(connection, query, mode, limit, offset, filters, fts):
    clauses, values = _filter_sql(filters)
    clauses.append("instr(folded,?) > 0")
    values.append(query)
    if mode != "all":
        clauses.append("kind=?")
        values.append(mode)
    if fts and len(query) >= 3:
        clauses.append(
            "rowid IN (SELECT rowid FROM search_fts WHERE search_fts MATCH ?)"
        )
        values.append('"' + query.replace('"', '""') + '"')
    where = " AND ".join(clauses)
    sql = f"SELECT body FROM documents WHERE {where} ORDER BY recordingId,coalesce(start,-1),rowid LIMIT ? OFFSET ?"
    rows = connection.execute(sql, [*values, limit + 1, offset]).fetchall()
    results = []
    for row in rows[:limit]:
        result = json.loads(row[0])
        result["excerpt"] = _excerpt(result.pop("text"), query)
        results.append(result)
    return results, len(rows) > limit


def _metadata_status(state, indexed_status, indexed_output):
    recording = state["recording"]
    ref = recording.get("transcript")
    if not ref:
        return "missing"
    if (
        state["source"] != recording["observation"]
        or state["source"] != ref.get("observation")
        or recording["availability"] != "available"
    ):
        return "stale"
    return indexed_status if state["output"] == indexed_output else "failed"


def _fresh_speech(service, state, result, query):
    if "validatedTranscript" not in state:
        state["validatedTranscript"] = _transcript(service, state)
    status, payload = state["validatedTranscript"]
    if payload is None:
        return None, status
    evidence = result["evidence"]
    start, end = evidence.get("wordStart"), evidence.get("wordEnd")
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(payload["words"])
    ):
        return None, "failed"
    words = payload["words"][start:end]
    if words[0]["start"] >= words[-1]["end"]:
        return None, "failed"
    text = " ".join(word["text"] for word in words)
    if query not in _fold(text):
        return None, status
    fresh = _document(
        state["recording"],
        state,
        result["generation"],
        "speech",
        text,
        words[0]["start"],
        words[-1]["end"],
        {**state["recording"]["transcript"], "wordStart": start, "wordEnd": end},
    )
    fresh["excerpt"] = _excerpt(fresh.pop("text"), query)
    return fresh, status


def _fresh_metadata(head, state, result, query):
    recording = state["recording"]
    fresh = _document(
        recording,
        state,
        result["generation"],
        "metadata",
        f"{recording['path']} {state['groupLabel']}",
        evidence={
            "inventoryRef": head["inventoryRef"],
            "recordingVersion": recording["version"],
        },
    )
    if query not in _fold(fresh["text"]):
        return None
    fresh["excerpt"] = _excerpt(fresh.pop("text"), query)
    return fresh


def _fresh_candidate(service, head, state, result, query, filters, observed, parents):
    if (
        result.get("generation") != _generation(head, service.root)
        or result.get("version") != state["recording"]["version"]
    ):
        return None
    identifier = state["recording"]["id"]
    if identifier not in observed:
        _observe_state(service, state, parents)
    index_status = result.get("indexedStatus", "missing")
    if result["matchType"] == "speech":
        fresh, status = _fresh_speech(service, state, result, query)
    else:
        status = _metadata_status(
            state, index_status, result.get("indexedOutputObservation")
        )
        fresh = _fresh_metadata(head, state, result, query)
    observed[identifier] = (index_status, status)
    if fresh is None or filters.get("transcriptStatus", status) != status:
        return None
    fresh["transcriptStatus"] = status
    return fresh


def _validated_candidates(
    service, head, lookup, candidates, query, filters, observed, parents, limit
):
    results = []
    consumed = 0
    for candidate in candidates:
        consumed += 1
        state = lookup.get(candidate["recordingId"])
        fresh = (
            _fresh_candidate(
                service, head, state, candidate, query, filters, observed, parents
            )
            if state
            else None
        )
        if fresh is not None:
            results.append(fresh)
        if len(results) == limit:
            break
    return results, consumed


def _fresh_page(
    service, head, states, connection, query, mode, limit, offset, filters, fts
):
    by_id = {state["recording"]["id"]: state for state in states}
    results, observed, parents = [], {}, {service.root}
    scanned, more = 0, True
    while more and len(results) < limit and scanned < 1000:
        candidates, following = _matches(
            connection, query, mode, min(100, 1000 - scanned), offset, filters, fts
        )
        fresh, consumed = _validated_candidates(
            service,
            head,
            by_id,
            candidates,
            query,
            filters,
            observed,
            parents,
            limit - len(results),
        )
        results.extend(fresh)
        offset += consumed
        scanned += consumed
        more = following or consumed < len(candidates)
    return results, more, offset, observed, scanned >= 1000 and more


def _observed_coverage(coverage, observed):
    updated = {
        **coverage,
        "indexCoverage": "snapshot",
        "freshnessScope": "returned-candidates",
        "observedRecordings": len(observed),
        "unobservedRecordings": coverage["totalRecordings"] - len(observed),
    }
    for indexed, current in observed.values():
        if indexed == "ready" and current != "ready":
            updated["speechSearchable"] -= 1
            updated["unsearchedSpeech"] += 1
        if current == "failed" and indexed != "failed":
            updated["invalidTranscripts"] += 1
        if current == "stale" and indexed != "stale":
            updated["staleTranscripts"] += 1
    return updated


def _unknown_filter_count(states, filters):
    duration = bool({"minDuration", "maxDuration"} & filters.keys())
    dates = bool({"dateFrom", "dateTo"} & filters.keys())
    return sum(
        (duration and state["recording"]["metadata"].get("durationSeconds") is None)
        or (dates and not state["recording"]["metadata"].get("recordingDate"))
        for state in states
    )


def search_library(service, query, *, mode="all", limit=20, cursor=None, filters=None):
    query, filters = _options(query, mode, limit, filters)
    head, states, generation, stamp = _snapshot(service, observe=False)
    context = content_hash(
        {
            "generation": generation,
            "query": query,
            "mode": mode,
            "limit": limit,
            "filters": filters,
        }
    )
    offset = _offset(cursor, context)
    connection, coverage, fts, limitations, persisted = _cache(
        service, head, states, generation, stamp
    )
    try:
        results, more, following_offset, observed, partial = _fresh_page(
            service, head, states, connection, query, mode, limit, offset, filters, fts
        )
    finally:
        connection.close()
    omitted = _unknown_filter_count(states, filters)
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps({"context": context, "offset": following_offset}).encode()
        ).decode()
        if more
        else None
    )
    return {
        "status": "partial" if partial else "ok",
        "generation": generation,
        "results": results,
        "nextCursor": next_cursor,
        "coverage": {
            **_observed_coverage(coverage, observed),
            "omittedUnknown": omitted,
            "backend": "sqlite-fts5" if fts else "sqlite",
            "persistentProjection": persisted,
            "limitations": limitations,
            "refreshRecommended": partial
            or any(indexed != current for indexed, current in observed.values()),
        },
    }
