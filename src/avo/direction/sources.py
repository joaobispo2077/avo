"""Bounded provider learning discovery, never historical media inspection."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from avo.direction.rules import DirectionError, seal, validate
from avo.timeline.contracts import (
    content_hash,
    document_hash_excluding,
    validate_document,
)

DOCUMENT_BYTES = 2 * 1024 * 1024
COLLECTION_BYTES = 16 * 1024 * 1024
NORMALIZATION_VERSION = "1.0.0"
_ENTRY_FILES = ("learndown.json", "catalogo.json", "README.md", "learndown.md")
_DIMENSIONS = [
    "editorial-voice",
    "creator-presence",
    "emotional-arc",
    "pacing",
    "visual-support",
    "motion",
    "evidence-inserts",
    "sound",
    "captions",
    "color",
    "avoidance",
]
_STATES = {"proposed", "executed", "observed", "approved", "rejected", "superseded"}


class _CreatorInstruction(dict):
    """Native-only marker following exact event schema and content-hash checks."""


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON value: {value}")


def normalize_text(value) -> str:
    """Versioned excerpt normalization; private locators are not artistic evidence."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*"
        r"(?:\"[^\"]*\"|'[^']*'|\S+)",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\n\"']+", "[project-path]", text)
    text = re.sub(
        r"(?<![:\w])/(?:home|mnt|Users|private|tmp|media|Volumes)/[^\n\"']+",
        "[project-path]",
        text,
    )
    return " ".join(text.split())


def _root(provider_root: Path, provider: str | None = None) -> Path:
    declared = Path(provider_root).absolute()
    if declared.is_symlink() or declared.resolve() != declared:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Provider root cannot be a symlink."
        )
    if provider is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", provider):
        raise DirectionError("DIR_INVALID_REFERENCE", "Invalid provider identity.")
    return declared.resolve()


def _contained(root: Path, relative: str) -> Path:
    relative = str(relative).replace("\\", "/")
    path = Path(relative)
    if path.is_absolute() or ":" in relative or ".." in path.parts:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Source path leaves the provider."
        )
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Source link leaves the provider."
        )
    return result


def _read(root: Path, relative: str, state: dict, role: str, timestamp: str) -> tuple:
    path = _contained(root, relative)
    if relative in state["cache"]:
        return state["cache"][relative]
    size = path.stat().st_size
    if size > DOCUMENT_BYTES:
        raise DirectionError("DIR_SOURCE_OVERSIZE", "Document exceeds 2 MiB.")
    if state["bytes"] + size > COLLECTION_BYTES:
        raise DirectionError("DIR_COLLECTION_OVERSIZE", "Collection exceeds 16 MiB.")
    with path.open("rb") as stream:
        allowance = min(DOCUMENT_BYTES, COLLECTION_BYTES - state["bytes"])
        raw = stream.read(allowance + 1)
    if len(raw) > allowance:
        raise DirectionError(
            "DIR_COLLECTION_OVERSIZE", "Source exceeds remaining collection capacity."
        )
    if len(raw) > DOCUMENT_BYTES:
        raise DirectionError("DIR_SOURCE_OVERSIZE", "Document grew beyond 2 MiB.")
    state["bytes"] += len(raw)
    text = raw.decode("utf-8-sig")
    value = (
        json.loads(text, parse_constant=_reject_constant)
        if path.suffix.lower() == ".json"
        else text
    )
    if path.suffix.lower() == ".json" and not isinstance(value, dict):
        raise ValueError("Recognized learning JSON must be an object.")
    metadata = {
        "path": relative,
        "byteHash": hashlib.sha256(raw).hexdigest(),
        "role": role,
        "sizeBytes": len(raw),
        "consumedSelectors": [],
        "inspectedAt": timestamp,
    }
    state["cache"][relative] = (value, metadata)
    return value, metadata


def _index(root: Path, state: dict, timestamp: str, provider: str) -> tuple:
    try:
        index, metadata = _read(
            root, "learndowns/index.json", state, "catalog-index", timestamp
        )
    except FileNotFoundError:
        return {}, None
    if not isinstance(index, dict) or index.get("provider", provider) != provider:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Learning catalog provider is invalid."
        )
    if not isinstance(index.get("entries", []), list):
        raise DirectionError(
            "DIR_SOURCE_UNAVAILABLE", "Learning catalog entries must be a list."
        )
    return {
        str(item["entryId"]): item
        for item in index.get("entries", [])
        if isinstance(item, dict) and item.get("entryId")
    }, metadata


def _discovered(root: Path, indexed: dict) -> list[str]:
    names = set(indexed)
    directory = _contained(root, "learndowns")
    if directory.is_dir():
        for child in directory.iterdir():
            if child.is_dir() and (
                any((child / name).exists() for name in _ENTRY_FILES)
                or (child / "timeline-learning/index.json").exists()
            ):
                names.add(child.name)
    return sorted(names)


def _snapshot_documents(root: Path, name: str, state: dict, timestamp: str) -> list:
    directory = f"learndowns/{name}/timeline-learning"
    index, index_meta = _read(
        root, f"{directory}/index.json", state, "snapshot-index", timestamp
    )
    if not isinstance(index, dict):
        raise DirectionError(
            "DIR_SOURCE_UNAVAILABLE", "Snapshot index is not an object."
        )
    documents = [(index, index_meta)]
    for reference in index.get("snapshots", []):
        filename = str(reference.get("path", ""))
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise DirectionError("DIR_INVALID_REFERENCE", "Snapshot path is invalid.")
        snapshot, metadata = _read(
            root, f"{directory}/{filename}", state, "timeline-snapshot", timestamp
        )
        validate_document(snapshot, "avo.timeline-learning.schema.json")
        actual = document_hash_excluding(snapshot, "snapshotHash")
        if actual != snapshot["snapshotHash"] or actual != reference.get(
            "snapshotHash"
        ):
            raise DirectionError(
                "DIR_SOURCE_CHANGED", "Snapshot hash does not match its content."
            )
        if snapshot["snapshotId"] != reference.get("snapshotId"):
            raise DirectionError(
                "DIR_SOURCE_CHANGED", "Snapshot identity does not match index."
            )
        metadata.update(
            parentSnapshotId=snapshot["snapshotId"], parentSnapshotHash=actual
        )
        documents.append((snapshot, metadata))
    return documents


def _entry_documents(root: Path, name: str, state: dict, timestamp: str) -> tuple:
    documents, issues = [], []
    directory = _contained(root, f"learndowns/{name}")
    for filename in _ENTRY_FILES:
        if not (directory / filename).exists():
            continue
        role = "structured-catalog" if filename == "catalogo.json" else "legacy-summary"
        try:
            documents.append(
                _read(root, f"learndowns/{name}/{filename}", state, role, timestamp)
            )
        except (OSError, ValueError, UnicodeError) as exc:
            issues.append((getattr(exc, "code", "unavailable"), str(exc)))
    if (directory / "timeline-learning/index.json").exists():
        try:
            documents.extend(_snapshot_documents(root, name, state, timestamp))
        except (OSError, ValueError, UnicodeError) as exc:
            issues.append((getattr(exc, "code", "unavailable"), str(exc)))
    return documents, issues


def _record_clues(value: dict) -> set:
    clues = set()
    raw = value.get("rawDir") or value.get("sourceRoot")
    if isinstance(raw, str) and raw.strip():
        normalized = (
            unicodedata.normalize("NFKC", raw).replace("\\", "/").rstrip("/").casefold()
        )
        clues.add("0-root:" + re.sub(r"^/mnt/([a-z])/", r"\1:/", normalized))
    for key in ("sourceProjectId", "videoId"):
        if isinstance(value.get(key), str) and value[key].strip():
            clues.add("1-project:" + value[key])
    fingerprint = value.get("masterFingerprint")
    if isinstance(fingerprint, dict) and re.fullmatch(
        r"[a-f0-9]{64}", str(fingerprint.get("sha256", ""))
    ):
        clues.add("2-master:" + str(fingerprint["sha256"]))
    return clues


def _identity_clues(index_entry: dict, documents: list) -> set:
    values = [
        index_entry,
        *(value for value, _ in documents if isinstance(value, dict)),
    ]
    return set().union(*(_record_clues(value) for value in values))


def _bases(names: set, private: dict) -> set:
    return {
        str(value.get("baseEntryId", ""))
        for name in names
        for value, _ in private[name]["documents"]
        if isinstance(value, dict)
    }


def _merge_group_once(groups: list, clues: dict, private: dict) -> bool:
    for i, left in enumerate(groups):
        for right in groups[i + 1 :]:
            overlap = set().union(*(clues[name] for name in left)) & set().union(
                *(clues[name] for name in right)
            )
            if (
                overlap
                or _bases(left, private) & right
                or _bases(right, private) & left
            ):
                left.update(right)
                groups.remove(right)
                return True
    return False


def _group_anchor(group: set, clues: dict, private: dict) -> str | None:
    # A declared continuation points back to an existing anchor. Its new aliases
    # must not replace the underlying project's identity or decision lineage.
    parents = _bases(group, private) & group
    anchors = sorted(parents) if parents else sorted(group)
    for name in anchors:
        if clues[name]:
            return min(clues[name])
    return None


def _annotate_group(group: set, clues: dict, private: dict, by_name: dict) -> None:
    anchor = _group_anchor(group, clues, private)
    identity = "project-" + content_hash(anchor)[:20] if anchor else None
    included = sorted(
        name for name in group if by_name[name]["disposition"] == "included"
    )
    for name in group:
        entry = by_name[name]
        entry.update(
            sourceProjectId=identity,
            identityBasis=anchor.split(":", 1)[0] if anchor else "unknown",
            identityUncertainty=[]
            if identity
            else ["No explicit source project identity."],
            relatedEntryIds=sorted(group - {name}),
        )
        if name in included[1:]:
            entry.update(
                disposition="related-revision",
                reason="Related source-project revision or derivative; not another vote.",
            )


def _group_identities(entries: list, private: dict) -> None:
    groups = [{entry["entryId"]} for entry in entries]
    clues = {
        name: _identity_clues(item["index"], item["documents"])
        for name, item in private.items()
    }
    while _merge_group_once(groups, clues, private):
        pass
    by_name = {entry["entryId"]: entry for entry in entries}
    for group in groups:
        _annotate_group(group, clues, private, by_name)


def _master_identity(bodies: list) -> dict | None:
    identity = {}
    for value in bodies:
        fingerprint = value.get("masterFingerprint")
        if isinstance(fingerprint, dict) and re.fullmatch(
            r"[a-f0-9]{64}", str(fingerprint.get("sha256", ""))
        ):
            identity.setdefault("sha256", fingerprint["sha256"])
        if value.get("masterBasename"):
            identity.setdefault("basename", normalize_text(value["masterBasename"]))
    return identity or None


def _entry_layout(roles: set) -> str:
    for role in ("timeline-snapshot", "structured-catalog", "legacy-summary"):
        if role in roles:
            return {"legacy-summary": "legacy-narrative"}.get(role, role)
    return "unknown"


def _entry_reason(documents: list, issues: list) -> str:
    if documents:
        return "Recognized bounded learning documents are available."
    return (
        normalize_text(issues[0][1])
        if issues
        else "No recognized learning document is accessible."
    )


def _completion(documents: list, status: str | None, roles: set) -> dict:
    snapshot_status = next(
        (
            value.get("status")
            for value, meta in documents
            if meta["role"] == "timeline-snapshot"
        ),
        None,
    )
    return {
        "catalogStatus": status,
        "snapshotStatus": snapshot_status,
        "observedFacts": sorted(roles),
    }


def _catalog_evidence(metadata, status: str | None):
    if not metadata:
        return None
    return {
        "path": metadata["path"],
        "byteHash": metadata["byteHash"],
        "declaredStatus": status or "unknown",
    }


def _entry(
    name: str, documents: list, issues: list, index_entry: dict, catalog_meta
) -> dict:
    bodies = [value for value, _ in documents if isinstance(value, dict)]
    roles = {metadata["role"] for _, metadata in documents}
    status = str(index_entry.get("status") or "") or None
    return {
        "entryId": name,
        "layout": _entry_layout(roles),
        "disposition": "included" if documents else "unavailable",
        "reason": _entry_reason(documents, issues),
        "completionEvidence": _completion(documents, status, roles),
        "sourceProjectId": None,
        "identityBasis": "unknown",
        "identityUncertainty": [],
        "derivativeContext": normalize_text(index_entry.get("title")) or None,
        "relatedEntryIds": [],
        "decisionLineageIds": [],
        "documents": [metadata for _, metadata in documents],
        "catalogEvidence": _catalog_evidence(catalog_meta, status),
        "recordedMasterIdentity": _master_identity(bodies),
    }


def _record_items(value, metadata: dict) -> list:
    if isinstance(value, str):
        lines = value.splitlines()
        return [
            (
                "narrative",
                "\n".join(lines),
                {
                    "kind": "markdown-lines",
                    "heading": "",
                    "startLine": 1,
                    "endLine": len(lines),
                },
                {},
            )
        ]
    if not isinstance(value, dict):
        return []
    items = []
    for key in ("summary",):
        if isinstance(value.get(key), str) and value[key].strip():
            items.append(
                (key, value[key], {"kind": "json-pointer", "pointer": f"/{key}"}, {})
            )
    note = (
        value.get("learning", {}).get("note")
        if isinstance(value.get("learning"), dict)
        else None
    )
    if note:
        items.append(
            (
                "learning-note",
                note,
                {"kind": "json-pointer", "pointer": "/learning/note"},
                {},
            )
        )
    items.extend(_structured_items(value))
    items.extend(_instruction_items(value))
    return items


def _instruction_items(value: dict) -> list:
    items = []
    for prefix, event in _creator_events(value):
        try:
            validate("CreatorDecision", event)
        except DirectionError:
            continue
        instruction = event.get("providerInstruction")
        if event["scope"] != "provider" or not instruction:
            continue
        source = _CreatorInstruction(
            {
                "status": "observed",
                "reportedAction": event["action"],
                "rationaleKind": "creator-recorded",
                "explicitInstruction": {
                    "source": normalize_text(event["humanInstruction"]["source"]),
                    "text": normalize_text(instruction["text"]),
                },
                "applicability": instruction["applicability"],
            }
        )
        source["applicability"] = _applicability(source["applicability"])
        source["applicability"]["exclusions"].extend(
            normalize_text(item) for item in instruction["exclusions"]
        )
        items.append(
            (
                event["id"],
                instruction["text"],
                {
                    "kind": "json-pointer",
                    "pointer": f"{prefix}/providerInstruction/text",
                },
                source,
            )
        )
    return items


def _creator_events(value: dict) -> list:
    if value.get("documentType") == "CreatorDecision":
        return [("", value)]
    events = value.get("creatorDecisions", [])
    return [
        (f"/creatorDecisions/{index}", event)
        for index, event in enumerate(events if isinstance(events, list) else [])
    ]


def _structured_items(value: dict) -> list:
    items = []
    for key in (
        "decisionOutcomes",
        "techniques",
        "techniqueCandidates",
        "preventionRules",
        "uncertainties",
    ):
        records = value.get(key, [])
        for i, record in enumerate(records if isinstance(records, list) else []):
            if isinstance(record, dict) and record.get("summary"):
                items.append(
                    (
                        str(record.get("id", f"{key}-{i}")),
                        record["summary"],
                        {"kind": "json-pointer", "pointer": f"/{key}/{i}/summary"},
                        record,
                    )
                )
    return items


def _verified_use(reference, identity: str, documents: list) -> tuple:
    if not isinstance(reference, dict):
        return None, None
    try:
        validate("DocumentRef", reference)
    except DirectionError:
        return None, None
    for value, metadata in documents:
        if metadata["path"] != reference["path"] or not isinstance(value, dict):
            continue
        for record_id, _, _, record in _structured_items(value):
            if (
                record_id == identity == reference["id"]
                and record.get("status") in {"executed", "observed", "approved"}
                and content_hash(record) == reference["documentHash"]
            ):
                return reference, record["status"]
    return None, None


def _applicability(value: dict) -> dict:
    result = {"formats": [], "sections": [], "conditions": [], "exclusions": []}
    if not isinstance(value, dict):
        return result
    for key in result:
        if isinstance(value.get(key), list):
            result[key] = [
                normalize_text(item) for item in value[key] if isinstance(item, str)
            ]
    return result


def _source_facts(source: dict, identity: str, documents: list) -> dict:
    reference, actual_state = _verified_use(
        source.get("useEvidence"), identity, documents
    )
    reported = source.get("status")
    state = reported if reported in _STATES else actual_state or "unknown"
    result = {
        "normalizedState": state,
        "useEvidence": reference,
        "approvalEvidence": None,
        "applicability": _applicability(source.get("applicability")),
        "rationaleKind": "creator-recorded"
        if isinstance(source, _CreatorInstruction)
        else "unknown",
    }
    if isinstance(source, _CreatorInstruction):
        result["explicitInstruction"] = source["explicitInstruction"]
    return result


def _reported_state(source: dict, value):
    if isinstance(source, _CreatorInstruction):
        return source["reportedAction"]
    if isinstance(value, dict):
        return str(source.get("status") or value.get("status") or "")
    return None


def _evidence(entry: dict, documents: list) -> list:
    records = []
    for value, metadata in documents:
        for identity, raw, selector, source in _record_items(value, metadata):
            excerpt = normalize_text(raw)[:1000]
            if not excerpt:
                continue
            lineage_source = source.get("decisionLineageId") or [
                entry["sourceProjectId"],
                identity,
            ]
            lineage = "decision-" + content_hash(lineage_source)[:20]
            record = {
                "evidenceId": "evidence-"
                + content_hash([entry["entryId"], metadata["path"], selector])[:20],
                "sourceProjectId": entry["sourceProjectId"],
                "entryId": entry["entryId"],
                "documentRef": {
                    key: metadata[key] for key in ("path", "byteHash", "role")
                },
                "selector": selector,
                "excerpt": excerpt,
                "excerptHash": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "normalizationVersion": NORMALIZATION_VERSION,
                "decisionLineageId": lineage,
                "reportedState": _reported_state(source, value),
                **_source_facts(source, identity, documents),
                "interpretation": "",
            }
            metadata["consumedSelectors"].append(selector)
            records.append(record)
    entry["decisionLineageIds"] = sorted(
        {record["decisionLineageId"] for record in records}
    )
    return records


def _load_entry(
    root: Path, name: str, state: dict, timestamp: str, provider: str
) -> tuple:
    if not re.fullmatch(r"[\w][\w.-]*", name, re.UNICODE):
        return [], [("invalid", "Entry identity is not a provider-relative name.")]
    try:
        documents, issues = _entry_documents(root, name, state, timestamp)
        for value, _ in documents:
            if isinstance(value, dict) and value.get("provider", provider) != provider:
                raise DirectionError(
                    "DIR_INVALID_REFERENCE", "Entry belongs to another provider."
                )
        return documents, issues
    except (OSError, ValueError, UnicodeError) as exc:
        return [], [(getattr(exc, "code", "unavailable"), str(exc))]


def _collect_rows(
    root: Path,
    indexed: dict,
    index_meta,
    state: dict,
    timestamp: str,
    provider: str,
    selected: set,
) -> tuple:
    rows, private, oversize = [], {}, set()
    problems = []
    for name in _discovered(root, indexed):
        documents, issues = (
            _load_entry(root, name, state, timestamp, provider)
            if name in selected
            else ([], [])
        )
        entry = _entry(name, documents, issues, indexed.get(name, {}), index_meta)
        if name not in selected:
            entry.update(
                disposition="excluded",
                reason="Not in the explicitly selected source subset.",
            )
        rows.append(entry)
        private[name] = {"documents": documents, "index": indexed.get(name, {})}
        if entry["disposition"] == "unavailable" and not issues:
            problems.append(f"{name}: {entry['reason']}")
        for code, reason in issues:
            problems.append(f"{name}: {normalize_text(reason)}")
            if "OVERSIZE" in code:
                oversize.add(name)
    _group_identities(rows, private)
    evidence = [
        record
        for entry in rows
        for record in _evidence(entry, private[entry["entryId"]]["documents"])
    ]
    return rows, evidence, problems, oversize


def _coverage(rows: list, oversize: set) -> dict:
    counts = Counter(row["disposition"] for row in rows)
    return {
        "discovered": len(rows),
        "included": counts["included"],
        "related": counts["related-revision"],
        "excluded": counts["excluded"],
        "unavailable": counts["unavailable"],
        "oversize": len(oversize),
        "distinctProjects": len(
            {
                row["sourceProjectId"]
                for row in rows
                if row["sourceProjectId"] and row["documents"]
            }
        ),
        "unknownDimensions": _DIMENSIONS,
    }


def _source_identity(rows: list) -> list:
    return [
        {
            "entryId": row["entryId"],
            "disposition": row["disposition"],
            "sourceProjectId": row["sourceProjectId"],
            "relatedEntryIds": row["relatedEntryIds"],
            "documents": [
                {"path": doc["path"], "byteHash": doc["byteHash"]}
                for doc in row["documents"]
            ],
        }
        for row in rows
    ]


def _semantic_identity(evidence: list) -> list:
    return sorted(
        {
            content_hash(
                {
                    key: record[key]
                    for key in (
                        "sourceProjectId",
                        "decisionLineageId",
                        "excerpt",
                        "normalizedState",
                        "rationaleKind",
                    )
                }
            )
            for record in evidence
        }
    )


def collect_sources(
    provider_root: Path, provider: str, *, entries=None, clock=None
) -> dict:
    """Collect the bounded union of catalog entries and recognized entry folders."""
    root = _root(provider_root, provider)
    timestamp = (
        clock()
        if clock
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    state = {"bytes": 0, "cache": {}}
    problems = []
    try:
        indexed, index_meta = _index(root, state, timestamp, provider)
    except (OSError, ValueError, UnicodeError) as exc:
        if getattr(exc, "code", None) == "DIR_INVALID_REFERENCE":
            raise
        indexed, index_meta = {}, None
        problems.append("Catalog unavailable: " + normalize_text(exc))
    discovered = _discovered(root, indexed)
    selected = set(discovered if entries is None else entries)
    if selected - set(discovered):
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Selected entry is not in this provider."
        )
    rows, evidence, issues, oversize = _collect_rows(
        root, indexed, index_meta, state, timestamp, provider, selected
    )
    normalized = _source_identity(rows)
    return seal(
        "SourceManifest",
        {
            "provider": provider,
            "collectionId": "collection-" + content_hash(normalized)[:20],
            "entries": rows,
            "evidenceRecords": evidence,
            "coverage": _coverage(rows, oversize),
            "sourceSetHash": content_hash(normalized),
            "semanticEvidenceHash": content_hash(_semantic_identity(evidence)),
            "limits": {
                "documentBytes": DOCUMENT_BYTES,
                "collectionBytes": COLLECTION_BYTES,
            },
            "partialReasons": sorted(set(problems + issues)),
        },
        clock=lambda: timestamp,
    )


def _changed_source(root: Path, document: dict) -> bool:
    path = _contained(root, document["path"])
    if path.stat().st_size > DOCUMENT_BYTES:
        raise OSError("Source exceeds document limit.")
    with path.open("rb") as stream:
        raw = stream.read(DOCUMENT_BYTES + 1)
    return (
        len(raw) > DOCUMENT_BYTES
        or hashlib.sha256(raw).hexdigest() != document["byteHash"]
    )


def _freshness_status(changed: set, unavailable: set, count: int) -> str:
    if changed:
        return "changed"
    if unavailable:
        return "partial" if len(unavailable) < count else "unavailable"
    return "current"


def check_freshness(provider_root: Path, manifest: dict) -> dict:
    """Recheck consumed small document bytes, including same-size/mtime edits."""
    validate("SourceManifest", manifest)
    root = _root(provider_root, manifest["provider"])
    changed, unavailable = set(), set()
    for entry in manifest["entries"]:
        for document in entry["documents"]:
            try:
                if _changed_source(root, document):
                    changed.add(entry["entryId"])
            except (OSError, ValueError):
                unavailable.add(entry["entryId"])
    return {
        "status": _freshness_status(changed, unavailable, len(manifest["entries"])),
        "affectedEntryIds": sorted(changed | unavailable),
        "changedEntryIds": sorted(changed),
        "unavailableEntryIds": sorted(unavailable),
    }


def read_reference(path: Path) -> dict:
    """Read only the explicitly supplied descriptor, never its media/URL locator."""
    try:
        path = Path(path)
        if path.stat().st_size > DOCUMENT_BYTES:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Reference descriptor exceeds 2 MiB."
            )
        with path.open("rb") as stream:
            raw = stream.read(DOCUMENT_BYTES + 1)
    except DirectionError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Cannot read reference descriptor."
        ) from exc
    if len(raw) > DOCUMENT_BYTES:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Reference descriptor exceeds 2 MiB."
        )
    try:
        value = json.loads(raw.decode("utf-8-sig"))
        validate("ReferenceDescriptor", value)
    except (ValueError, UnicodeError) as exc:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Invalid reference descriptor."
        ) from exc
    return value
