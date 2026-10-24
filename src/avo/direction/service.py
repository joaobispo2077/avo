"""Provider artistic proposals and exact creator decisions, without media jobs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from avo.direction.rules import (
    DirectionError,
    document_ref,
    seal,
    validate,
    validate_statement,
    visible_word_count,
)
from avo.direction.sources import (
    DOCUMENT_BYTES,
    _contained,
    _evidence,
    _read,
    _root,
    check_freshness,
    collect_sources,
    normalize_text,
)
from avo.direction.store import DirectionStore
from avo.timeline.contracts import content_hash

PACKET_WORDS = 24000
MAX_DOCUMENT_BYTES = DOCUMENT_BYTES
_CANDIDATE_FIELDS = (
    "summary",
    "statements",
    "variants",
    "avoidances",
    "dimensionCoverage",
    "changeSummary",
)
_DISPOSITIONS = {
    "accept": "accepted",
    "reject": "rejected",
    "edit": "edited",
    "defer": "deferred",
    "qualify": "qualified",
}


def _event_action(event: dict, statement_id: str) -> str:
    for item in event.get("statementDispositions", []):
        if item["statementId"] == statement_id:
            return item["action"]
    return event["action"]


def _validate_identities(statements: list) -> None:
    for field in ("statementId", "lineageId"):
        values = [item[field] for item in statements]
        if len(values) != len(set(values)):
            raise DirectionError(
                "DIR_INVALID_REQUEST",
                "Statement and lineage identities must be unique.",
            )


def _validate_private_prose(value) -> None:
    if isinstance(value, str):
        normalized = normalize_text(value)
        if any(
            normalized.count(marker) > value.count(marker)
            for marker in ("[redacted]", "[project-path]")
        ):
            raise DirectionError(
                "DIR_INVALID_REQUEST",
                "Reusable provider prose must exclude credentials and private paths.",
            )
    elif isinstance(value, dict):
        for nested in value.values():
            _validate_private_prose(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_private_prose(nested)


def _validate_dispositions(profile: dict, request: dict) -> None:
    known = {item["statementId"] for item in profile["statements"]}
    selected = [
        item["statementId"] for item in request.get("statementDispositions", [])
    ]
    if len(selected) != len(set(selected)) or not set(selected) <= known:
        raise DirectionError(
            "DIR_INVALID_REFERENCE",
            "Each disposition must name a unique existing statement.",
        )
    if request.get("edits") and request["action"] not in {"edit", "qualify"}:
        raise DirectionError(
            "DIR_APPROVAL_SCOPE", "Changed statements require an edit or qualification."
        )


def _apply_statement_changes(statements: list, changes: list) -> list:
    by_id = {item["statementId"]: copy.deepcopy(item) for item in statements}
    for change in changes:
        if change["statementId"] not in by_id:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Disposition cites an unknown statement."
            )
        item = by_id[change["statementId"]]
        if change.get("text"):
            item["text"] = change["text"]
        if change.get("qualification"):
            item["applicability"].setdefault("conditions", []).append(
                change["qualification"]
            )
        if change["action"] == "reject":
            del by_id[change["statementId"]]
    return list(by_id.values())


def _entry_digests(manifest: dict) -> dict:
    return {
        row["entryId"]: content_hash(
            {
                "project": row["sourceProjectId"],
                "disposition": row["disposition"],
                "documents": [
                    {"path": document["path"], "byteHash": document["byteHash"]}
                    for document in row["documents"]
                ],
            }
        )
        for row in manifest["entries"]
    }


def _impacted_statements(parent: dict, previous: dict, affected: set) -> list:
    evidence = {
        item["evidenceId"]: item["entryId"] for item in previous["evidenceRecords"]
    }
    return [
        item["statementId"]
        for item in parent["statements"]
        if any(
            evidence.get(identifier) in affected for identifier in item["evidenceIds"]
        )
    ]


def _size(value: dict) -> int:
    return (
        len(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
        )
        + 1
    )


def _fields(document: dict) -> dict:
    return {
        key: copy.deepcopy(value)
        for key, value in document.items()
        if key
        not in {
            "id",
            "createdAt",
            "createdBy",
            "documentHash",
            "schemaVersion",
            "documentType",
        }
    }


def _envelope_body(document: dict) -> dict:
    return {
        key: value
        for key, value in document.items()
        if key not in {"createdAt", "documentHash"}
    }


def _native_meanings(records: list) -> set:
    return {
        content_hash(
            {"text": record["excerpt"], "applicability": record["applicability"]}
        )
        for record in records
        if record["entryId"] == "provider-direction"
        and record.get("explicitInstruction")
    }


def _chunks(items: list, build, fits) -> list:
    groups, current = [], []
    for item in items:
        candidate = current + [item]
        if fits(build(candidate)):
            current = candidate
            continue
        if current:
            groups.append(current)
        current = [item]
        if not fits(build(current)):
            raise DirectionError(
                "DIR_PACKET_LIMIT",
                "One source exceeds a bounded partition; select narrower learning.",
            )
    if current:
        groups.append(current)
    return groups


def _preview(kind: str, fields: dict) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "documentType": kind,
        "id": "preview",
        "createdAt": "preview",
        "createdBy": {"type": "native", "id": "avo.direction"},
        "documentHash": "0" * 64,
        **fields,
    }


def _schema(kind: str) -> str:
    return "avo.direction.schema.json#/$defs/" + kind


class DirectionService:
    """One provider's document service; acceptance never transfers to a film."""

    def __init__(self, provider_root: Path, provider: str, *, clock=None):
        self.root = _root(provider_root, provider)
        self.provider = provider
        self.clock = clock
        if (self.root / "direction").resolve() != self.root / "direction":
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Direction storage root cannot be a redirected link.",
            )
        self.store = DirectionStore(_contained(self.root, "direction"))

    def _result(self, operation: str, status: str = "ok", **fields) -> dict:
        return {
            "operation": "direction." + operation,
            "status": status,
            "provider": self.provider,
            "videoId": None,
            "refs": {},
            "coverage": {},
            "warnings": [],
            "nextAction": None,
            **fields,
        }

    def _index(self) -> dict:
        index = self.store.load_index()
        if index is not None and index.get("provider") != self.provider:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Direction index belongs to another provider."
            )
        return index or {
            "schemaVersion": "1.0.0",
            "documentType": "ProviderIndex",
            "provider": self.provider,
            "profiles": {},
        }

    def _load(self, reference: dict, kind: str) -> dict:
        validate("DocumentRef", reference)
        document = self.store.load_document(reference["path"], _schema(kind))
        if document_ref(document, reference["path"]) != reference:
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Exact document reference changed.",
                status="stale",
            )
        if document.get("provider", self.provider) != self.provider:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Document belongs to another provider."
            )
        return document

    def _store(self, document: dict, folder: str) -> dict:
        path = f"{folder}/{content_hash(_envelope_body(document))}.json"
        document = self._recover_envelope(document, path)
        return self.store.write_document(
            path, document, _schema(document["documentType"])
        )

    def _recover_envelope(self, document: dict, relative: str) -> dict:
        if not _contained(self.store.root, relative).is_file():
            return document
        existing = self.store.load_document(relative, _schema(document["documentType"]))
        if _envelope_body(existing) != _envelope_body(document):
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Uncommitted document belongs to a different request or immutable body.",
                status="conflict",
            )
        return existing

    def _manifest(self, manifest: dict) -> dict:
        if _size(manifest) <= MAX_DOCUMENT_BYTES:
            return self._store(manifest, "collections")
        base = _fields(manifest)
        base.update(
            entries=[],
            evidenceRecords=[],
            partialReasons=["Evidence is preserved in bounded manifest partitions."],
        )
        rows = copy.deepcopy(manifest["entries"])
        for row in rows:
            for document in row["documents"]:
                document["consumedSelectors"] = []
        refs = []
        for field, items in (
            ("entries", rows),
            ("evidenceRecords", manifest["evidenceRecords"]),
        ):

            def build(group, field=field):
                return _preview("SourceManifest", {**base, field: group})

            groups = _chunks(items, build, lambda doc: _size(doc) <= MAX_DOCUMENT_BYTES)
            for group in groups:
                part = seal("SourceManifest", {**base, field: group}, clock=self.clock)
                refs.append(self._store(part, "collections"))
        aggregate = seal(
            "SourceManifest", {**base, "partitionRefs": refs}, clock=self.clock
        )
        if _size(aggregate) > MAX_DOCUMENT_BYTES:
            raise DirectionError(
                "DIR_PACKET_LIMIT",
                "Manifest references need a narrower source selection.",
            )
        return self._store(aggregate, "collections")

    def _manifest_content(self, reference: dict, seen=None) -> dict:
        seen = set() if seen is None else seen
        if reference["documentHash"] in seen:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Manifest partition cycle or duplicate."
            )
        seen.add(reference["documentHash"])
        manifest = self._load(reference, "SourceManifest")
        entries = {row["entryId"]: row for row in manifest["entries"]}
        records = {
            record["evidenceId"]: record for record in manifest["evidenceRecords"]
        }
        for child_ref in manifest.get("partitionRefs", []):
            child = self._manifest_content(child_ref, seen)
            if child["sourceSetHash"] != manifest["sourceSetHash"]:
                raise DirectionError(
                    "DIR_SOURCE_CHANGED", "Manifest partition source identity differs."
                )
            entries.update({row["entryId"]: row for row in child["entries"]})
            records.update(
                {record["evidenceId"]: record for record in child["evidenceRecords"]}
            )
        return {
            **manifest,
            "entries": sorted(entries.values(), key=lambda row: row["entryId"]),
            "evidenceRecords": sorted(
                records.values(), key=lambda record: record["evidenceId"]
            ),
        }

    def _packet_content(self, reference: dict, seen=None) -> dict:
        seen = set() if seen is None else seen
        if reference["documentHash"] in seen:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Packet partition cycle or duplicate."
            )
        seen.add(reference["documentHash"])
        packet = self._load(reference, "ProviderInputPacket")
        records = {record["evidenceId"]: record for record in packet["evidenceRecords"]}
        for child_ref in packet.get("partitionRefs", []):
            child = self._packet_content(child_ref, seen)
            for key in (
                "profileId",
                "sourceManifestRef",
                "sourceSetHash",
                "expectedIndexHash",
                "brandGuideRef",
                "providerDecisionRefs",
                "parentRef",
                "statementLineages",
                "refreshReportRef",
            ):
                if packet.get(key) != child.get(key):
                    raise DirectionError(
                        "DIR_SOURCE_CHANGED", "Packet partition authority differs."
                    )
            for record in child["evidenceRecords"]:
                if (
                    record["evidenceId"] in records
                    and records[record["evidenceId"]] != record
                ):
                    raise DirectionError(
                        "DIR_SOURCE_CHANGED", "Conflicting partition evidence identity."
                    )
                records[record["evidenceId"]] = record
        return {
            **packet,
            "evidenceRecords": sorted(
                records.values(), key=lambda record: record["evidenceId"]
            ),
        }

    def _packet(self, fields: dict, brand_words: int) -> tuple:
        def fits(value):
            return (
                visible_word_count(json.dumps(value, ensure_ascii=False)) + brand_words
                <= PACKET_WORDS
                and _size(value) <= MAX_DOCUMENT_BYTES
            )

        if fits(_preview("ProviderInputPacket", fields)):
            return self._store(
                seal("ProviderInputPacket", fields, clock=self.clock), "collections"
            ), []
        base = {**fields, "evidenceRecords": []}
        groups = _chunks(
            fields["evidenceRecords"],
            lambda records: _preview(
                "ProviderInputPacket", {**base, "evidenceRecords": records}
            ),
            fits,
        )
        refs = [
            self._store(
                seal(
                    "ProviderInputPacket",
                    {**base, "evidenceRecords": records},
                    clock=self.clock,
                ),
                "collections",
            )
            for records in groups
        ]
        aggregate = {
            **base,
            "partitionRefs": refs,
            "globalCoverage": fields["coverage"],
        }
        if not fits(_preview("ProviderInputPacket", aggregate)):
            raise DirectionError(
                "DIR_PACKET_LIMIT",
                "Packet references exceed capacity; narrow selected entries.",
            )
        return self._store(
            seal("ProviderInputPacket", aggregate, clock=self.clock), "collections"
        ), [
            "Authoring evidence is partitioned; all children belong to the same global source coverage."
        ]

    def _brand(self) -> tuple:
        path = _contained(self.root, "DESIGN.md")
        if not path.is_file():
            return None, [
                "Authored brand guide is unavailable; no inferred guide replaces it."
            ]
        if path.stat().st_size > DOCUMENT_BYTES:
            return None, ["Authored brand guide exceeds the bounded input limit."]
        with path.open("rb") as stream:
            raw = stream.read(DOCUMENT_BYTES + 1)
        if len(raw) > DOCUMENT_BYTES:
            return None, ["Authored brand guide grew beyond the input limit."]
        document = seal(
            "BrandGuideSnapshot",
            {
                "provider": self.provider,
                "text": normalize_text(raw.decode("utf-8-sig")),
                "source": {
                    "path": "DESIGN.md",
                    "byteHash": hashlib.sha256(raw).hexdigest(),
                },
                "normalizationVersion": "1.0.0",
            },
            clock=self.clock,
        )
        if _size(document) > MAX_DOCUMENT_BYTES:
            return None, [
                "Authored brand snapshot exceeds the storage limit and remains a separate source."
            ]
        return self._store(document, "collections"), []

    def catalog(self) -> dict:
        index = self._index()
        return self._result(
            "catalog",
            profiles=copy.deepcopy(index.get("profiles", {})),
            expectedIndexHash=self.store.index_hash(),
        )

    def _decision_refs(self, profile_id: str) -> list:
        return copy.deepcopy(
            self._index()
            .get("profiles", {})
            .get(profile_id, {})
            .get("decisionRefs", [])
        )

    def _native_records(self, references: list) -> list:
        records = []
        for reference in references:
            event = self._load(reference, "CreatorDecision")
            with _contained(self.store.root, reference["path"]).open("rb") as stream:
                raw = stream.read(DOCUMENT_BYTES + 1)
            if len(raw) > DOCUMENT_BYTES or json.loads(raw) != event:
                raise DirectionError(
                    "DIR_SOURCE_CHANGED",
                    "Native decision bytes changed.",
                    status="stale",
                )
            metadata = {
                "path": "direction/" + reference["path"],
                "role": "provider-creator-decision",
                "byteHash": hashlib.sha256(raw).hexdigest(),
                "consumedSelectors": [],
            }
            entry = {"entryId": "provider-direction", "sourceProjectId": None}
            records.extend(_evidence(entry, [(event, metadata)]))
        return records

    def _lineages(self, profile_id: str, parent: dict | None) -> list:
        lineages = {
            item["lineageId"]: copy.deepcopy(item)
            for item in (parent or {}).get("statements", [])
        }
        for reference in self._decision_refs(profile_id):
            event = self._load(reference, "CreatorDecision")
            target = self._load(event["targetRef"], "ProviderProfileVersion")
            statements = (event.get("edits") or target)["statements"]
            if event["action"] == "qualify":
                statements = _apply_statement_changes(
                    statements, event.get("statementDispositions", [])
                )
            for item in statements:
                lineage = item["lineageId"]
                previous = lineages.get(lineage)
                if (
                    event["action"] in {"accept", "edit", "qualify"}
                    or lineage not in lineages
                ):
                    lineages[lineage] = copy.deepcopy(item)
                lineages[lineage]["creatorDispositionRef"] = self._lineage_reference(
                    previous, event, item, reference
                )
        return list(lineages.values())

    def _lineage_reference(
        self, previous, event: dict, item: dict, reference: dict
    ) -> dict:
        if (
            previous
            and previous.get("creatorDispositionRef")
            and _event_action(event, item["statementId"]) in {"accept", "defer"}
        ):
            prior_ref = previous["creatorDispositionRef"]
            prior = self._load(prior_ref, "CreatorDecision")
            if _event_action(prior, previous["statementId"]) in {"edit", "qualify"}:
                return prior_ref
        return reference

    def _refresh_report(
        self, parent: dict, manifest: dict, manifest_ref: dict, lineages: list
    ) -> dict:
        previous = self._manifest_content(parent["sourceManifestRef"])
        before, after = _entry_digests(previous), _entry_digests(manifest)
        changed = sorted(
            key for key in before.keys() & after.keys() if before[key] != after[key]
        )
        unavailable = sorted(
            row["entryId"]
            for row in manifest["entries"]
            if row["disposition"] == "unavailable"
        )
        impacted = _impacted_statements(parent, previous, set(changed + unavailable))
        return seal(
            "RefreshReport",
            {
                "provider": self.provider,
                "previousManifestRef": parent["sourceManifestRef"],
                "nextManifestRef": manifest_ref,
                "changedEntries": changed,
                "newEntries": sorted(after.keys() - before.keys()),
                "unavailableEntries": unavailable,
                "supersededEntries": sorted(before.keys() - after.keys()),
                "impactedStatements": impacted,
                "preservedDispositions": [
                    item["statementId"]
                    for item in lineages
                    if item.get("creatorDispositionRef")
                ],
                "conflicts": [],
                "bookkeepingOnly": before != after
                and previous["semanticEvidenceHash"] == manifest["semanticEvidenceHash"]
                and self._same_native_meaning(parent, lineages),
                "proposedProfileRef": None,
            },
            clock=self.clock,
        )

    def _constraint_meanings(self, lineages: list) -> set:
        meanings = set()
        for item in lineages:
            if item.get("creatorDispositionRef") is None:
                continue
            event = self._load(item["creatorDispositionRef"], "CreatorDecision")
            action = _event_action(event, item["statementId"])
            if action in {"edit", "qualify", "reject"}:
                meanings.add(
                    content_hash(
                        {
                            "action": action,
                            **{
                                key: item[key]
                                for key in (
                                    "lineageId",
                                    "text",
                                    "applicability",
                                    "exclusions",
                                )
                            },
                        }
                    )
                )
        return meanings

    def _same_native_meaning(self, parent: dict, lineages: list) -> bool:
        previous = self._packet_content(
            self._cached_packet(parent["synthesisProvenance"]["packetHash"])
        )
        current = self._native_records(self._decision_refs(parent["profileId"]))
        return _native_meanings(previous["evidenceRecords"]) == _native_meanings(
            current
        ) and self._constraint_meanings(
            parent["statements"]
        ) == self._constraint_meanings(lineages)

    def _parent(self, profile_id: str, refresh_from) -> tuple:
        if refresh_from is None:
            return None, None
        shown = self.show(refresh_from)
        if shown["profile"]["profileId"] != profile_id:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Refresh parent must belong to this profile."
            )
        return shown["profile"], shown["refs"]["profile"]

    def prepare(self, profile_id: str, *, entries=None, refresh_from=None) -> dict:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", profile_id):
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Invalid provider profile ID."
            )
        parent, parent_ref = self._parent(profile_id, refresh_from)
        manifest = collect_sources(
            self.root, self.provider, entries=entries, clock=self.clock
        )
        manifest_ref = self._manifest(manifest)
        decision_refs = self._decision_refs(profile_id)
        lineages = self._lineages(profile_id, parent)
        report_ref = (
            self._store(
                self._refresh_report(parent, manifest, manifest_ref, lineages),
                "refresh",
            )
            if parent
            else None
        )
        brand_ref, warnings = self._brand()
        brand_words = (
            visible_word_count(self._load(brand_ref, "BrandGuideSnapshot")["text"])
            if brand_ref
            else 0
        )
        if brand_words > max(0, PACKET_WORDS - 400):
            brand_ref, brand_words = None, 0
            warnings.append(
                "Authored brand context exceeds packet capacity; inspect it separately before resolving brand conflicts. It remains unchanged."
            )
        expected = self.store.index_hash()
        packet_ref, partition_warnings = self._packet(
            {
                "provider": self.provider,
                "profileId": profile_id,
                "parentRef": parent_ref,
                "sourceManifestRef": manifest_ref,
                "sourceSetHash": manifest["sourceSetHash"],
                "brandGuideRef": brand_ref,
                "statementLineages": lineages,
                "providerDecisionRefs": decision_refs,
                "refreshReportRef": report_ref,
                "evidenceRecords": manifest["evidenceRecords"]
                + self._native_records(decision_refs),
                "coverage": manifest["coverage"],
                "limits": {"packetWords": PACKET_WORDS},
                "submissionTemplateVersion": "1.0.0",
                "expectedIndexHash": expected,
            },
            brand_words,
        )
        return self._result(
            "prepare",
            "needs-authoring",
            refs={
                "packet": packet_ref,
                "manifest": manifest_ref,
                **({"refreshReport": report_ref} if report_ref else {}),
            },
            coverage=manifest["coverage"],
            warnings=warnings + partition_warnings + manifest["partialReasons"],
            expectedIndexHash=expected,
            nextAction="Author a structured proposal from this exact packet.",
        )

    def _verify_packet(self, request: dict) -> tuple:
        packet = self._packet_content(request["packetRef"])
        if request["expectedIndexHash"] != packet["expectedIndexHash"]:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Proposal changed the packet's expected index.",
                status="conflict",
            )
        manifest = self._manifest_content(packet["sourceManifestRef"])
        selected = [
            row["entryId"]
            for row in manifest["entries"]
            if row["disposition"] != "excluded"
        ]
        actual = collect_sources(
            self.root, self.provider, entries=selected, clock=self.clock
        )
        if (
            actual["sourceSetHash"] != manifest["sourceSetHash"]
            or packet["sourceSetHash"] != actual["sourceSetHash"]
            or packet["coverage"] != actual["coverage"]
        ):
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Consumed learning documents changed; prepare again.",
                status="stale",
            )
        native_records = self._verify_history(packet)
        records = {
            record["evidenceId"]: record
            for record in actual["evidenceRecords"] + native_records
        }
        for record in packet["evidenceRecords"]:
            if records.get(record["evidenceId"]) != record:
                raise DirectionError(
                    "DIR_SOURCE_CHANGED",
                    "Packet evidence or original selector content changed.",
                    status="stale",
                )
        self._verify_brand(packet.get("brandGuideRef"))
        return packet, manifest

    def _verify_history(self, packet: dict) -> list:
        refs = self._decision_refs(packet["profileId"])
        if packet.get("providerDecisionRefs", []) != refs:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Provider decision history changed or was omitted.",
                status="conflict",
            )
        parent = (
            self._load(packet["parentRef"], "ProviderProfileVersion")
            if packet.get("parentRef")
            else None
        )
        if packet.get("statementLineages", []) != self._lineages(
            packet["profileId"], parent
        ):
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "Packet omitted or modified existing creator dispositions.",
            )
        return self._native_records(refs)

    def _verify_brand(self, reference: dict | None) -> None:
        if reference is None:
            return
        brand = self._load(reference, "BrandGuideSnapshot")
        path = _contained(self.root, brand["source"]["path"])
        try:
            with path.open("rb") as stream:
                raw = stream.read(DOCUMENT_BYTES + 1)
        except OSError as exc:
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Authored brand source is unavailable.",
                status="stale",
            ) from exc
        if (
            hashlib.sha256(raw).hexdigest() != brand["source"]["byteHash"]
            or normalize_text(raw.decode("utf-8-sig")) != brand["text"]
        ):
            raise DirectionError(
                "DIR_SOURCE_CHANGED", "Authored brand source changed.", status="stale"
            )

    @staticmethod
    def _request_identity(kind: str, request: dict) -> tuple:
        prefix = kind + "-" + content_hash(request["requestId"]) + "-"
        return prefix, prefix + content_hash(request)

    def _replay(self, kind: str, request: dict) -> dict | None:
        prefix, identity = self._request_identity(kind, request)
        index = self._index()
        for state in index.get("profiles", {}).values():
            refs = (
                state.get("revisionRefs", [])
                if kind == "profile"
                else state.get("decisionRefs", [])
            )
            for ref in refs:
                if str(ref["id"]).startswith(prefix):
                    if ref["id"] != identity:
                        raise DirectionError(
                            "DIR_INDEX_CONFLICT",
                            "Request ID was reused with different content.",
                            status="conflict",
                        )
                    return ref
        return None

    def _request_result_hash(self, request_id: str) -> str:
        result = self.store.request_result(request_id)
        if result is None:
            raise DirectionError(
                "DIR_INDEX_CONFLICT", "Committed request has no exact result snapshot."
            )
        return result["indexHash"]

    def _profile(self, packet: dict, request: dict, *, preserve_history=True) -> dict:
        candidate = copy.deepcopy(request["candidate"])
        _validate_private_prose(candidate)
        _validate_identities(candidate["statements"])
        if visible_word_count(candidate["summary"]) > 500:
            raise DirectionError(
                "DIR_WORD_LIMIT", "Provider short view exceeds 500 visible words."
            )
        records = {record["evidenceId"]: record for record in packet["evidenceRecords"]}
        for statement in candidate["statements"]:
            if statement["basis"] in {"avo-default", "reference-suggestion"}:
                raise DirectionError(
                    "DIR_INVALID_REFERENCE",
                    "Provider learning packets do not establish a built-in or supplied-reference basis; use Briefstart for those sources.",
                )
            validate_statement(statement, records)
            if preserve_history:
                self._preserve_statement(statement, packet)
        provenance = request["synthesisProvenance"]
        if provenance.get("packetHash") != request["packetRef"]["documentHash"]:
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Authoring provenance must cite this exact packet.",
                status="stale",
            )
        state = self._index().get("profiles", {}).get(packet["profileId"], {})
        revision = f"r{len(state.get('revisionRefs', [])) + 1:04d}"
        profile = seal(
            "ProviderProfileVersion",
            {
                "id": self._request_identity("profile", request)[1],
                "provider": self.provider,
                "profileId": packet["profileId"],
                "revisionId": revision,
                "parentRef": packet.get("parentRef"),
                "sourceManifestRef": packet["sourceManifestRef"],
                "sourceSetHash": packet["sourceSetHash"],
                "brandGuideRef": packet.get("brandGuideRef"),
                **candidate,
                "synthesisProvenance": provenance,
                "refreshReportRef": packet.get("refreshReportRef"),
            },
            clock=self.clock,
        )
        relative = f"profiles/{profile['profileId']}/{profile['revisionId']}.json"
        return self._recover_envelope(profile, relative)

    def _preserve_statement(self, statement: dict, packet: dict) -> None:
        history = {
            item["lineageId"]: item for item in packet.get("statementLineages", [])
        }
        prior = history.get(statement["lineageId"], {})
        reference = prior.get("creatorDispositionRef")
        if statement.get("creatorDispositionRef") not in (None, reference):
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "New proposal cannot manufacture creator disposition.",
            )
        if reference is None:
            return
        event = self._load(reference, "CreatorDecision")
        action = _event_action(event, prior["statementId"])
        if action == "reject":
            raise DirectionError(
                "DIR_APPROVAL_SCOPE", "Rejected known lineage cannot silently reappear."
            )
        if action in {"edit", "qualify"} and any(
            statement[key] != prior[key]
            for key in ("text", "applicability", "exclusions")
        ):
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "Creator edits and qualifications must be preserved.",
            )
        statement["creatorDispositionRef"] = reference

    def _view(self, profile: dict) -> list:
        relative = f"views/{profile['profileId']}-{profile['revisionId']}.md"
        try:
            path = _contained(self.store.root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            evidence = "\n".join(
                f"- {item['text']} (basis: {item['basis']}; scope: {json.dumps(item['applicability'])})"
                for item in profile["statements"]
            )
            path.write_text(
                profile["summary"]
                + "\n\n## Evidence and detailed guidance\n\n"
                + evidence
                + "\n",
                encoding="utf-8",
            )
        except (OSError, ValueError):
            return [
                "Derived Markdown could not be written; accepted JSON authority is intact."
            ]
        return []

    def propose(self, request: dict) -> dict:
        validate("ProviderProposeRequest", request)
        replay = self._replay("profile", request)
        if replay:
            return self._result(
                "propose",
                "needs-review",
                refs={"proposal": replay},
                expectedIndexHash=self._request_result_hash(request["requestId"]),
            )
        packet, manifest = self._verify_packet(request)
        profile = self._profile(packet, request)
        relative = f"profiles/{profile['profileId']}/{profile['revisionId']}.json"
        reference = document_ref(profile, relative)
        index = self._index()
        state = index.setdefault("profiles", {}).setdefault(
            profile["profileId"],
            {
                "revisionRefs": [],
                "proposedRefs": [],
                "acceptedRef": None,
                "decisionRefs": [],
            },
        )
        state["revisionRefs"].append(reference)
        state["proposedRefs"].append(reference)
        result = self.store.publish(
            expected_index_hash=request["expectedIndexHash"],
            request_id=request["requestId"],
            documents=[(relative, profile, _schema("ProviderProfileVersion"))],
            index=index,
        )
        return self._result(
            "propose",
            "needs-review",
            refs={"proposal": reference},
            coverage=manifest["coverage"],
            warnings=self._view(profile),
            expectedIndexHash=result["indexHash"],
            nextAction="Creator review of this exact proposal.",
        )

    def _state_for(self, reference: dict, profile: dict) -> tuple:
        index = self._index()
        state = index.get("profiles", {}).get(profile["profileId"], {})
        if reference not in state.get("revisionRefs", []):
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Profile is not an indexed provider proposal."
            )
        return index, state

    def _cached_packet(self, digest: str) -> dict:
        state = {"cache": {}, "bytes": 0}
        for count, path in enumerate((self.store.root / "collections").glob("*.json")):
            if count >= 4096:
                break
            relative = path.relative_to(self.store.root).as_posix()
            value, _ = _read(self.store.root, relative, state, "cached-packet", "retry")
            if value.get("documentHash") == digest:
                validate("ProviderInputPacket", value)
                return document_ref(value, relative)
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "Exact cached authoring packet is unavailable."
        )

    def _edit_context(self, original: dict, request: dict) -> tuple:
        state = self._index()["profiles"][original["profileId"]]
        revision = f"r{len(state['revisionRefs']) + 1:04d}"
        relative = f"profiles/{original['profileId']}/{revision}.json"
        if _contained(self.store.root, relative).is_file():
            orphan = self.store.load_document(
                relative, _schema("ProviderProfileVersion")
            )
            reference = self._cached_packet(orphan["synthesisProvenance"]["packetHash"])
            packet, _ = self._verify_packet(
                {
                    "packetRef": reference,
                    "expectedIndexHash": request["expectedIndexHash"],
                }
            )
            return packet, reference
        prepared = self.prepare(
            original["profileId"],
            refresh_from=f"{original['profileId']}@{original['revisionId']}",
        )
        return self._packet_content(prepared["refs"]["packet"]), prepared["refs"][
            "packet"
        ]

    def _edited_profile(self, original: dict, request: dict, event_ref: dict) -> dict:
        candidate = copy.deepcopy(
            request.get("edits")
            or {key: original.get(key, []) for key in _CANDIDATE_FIELDS}
        )
        candidate["statements"] = _apply_statement_changes(
            candidate["statements"], request.get("statementDispositions", [])
        )
        if candidate == {key: original.get(key, []) for key in _CANDIDATE_FIELDS}:
            raise DirectionError(
                "DIR_INVALID_REQUEST",
                "Edit/qualify requires explicit changed content or a qualification.",
            )
        old_manifest = self._manifest_content(original["sourceManifestRef"])
        if (
            check_freshness(
                self.root,
                seal("SourceManifest", _fields(old_manifest), clock=self.clock),
            )["status"]
            != "current"
        ):
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Refresh changed source evidence before editing the profile.",
                status="stale",
            )
        packet, packet_ref = self._edit_context(original, request)
        for statement in candidate["statements"]:
            statement["creatorDispositionRef"] = event_ref
        authoring = {
            "requestId": "edit-" + request["requestId"],
            "packetRef": packet_ref,
            "candidate": candidate,
            "synthesisProvenance": {
                "executionKind": "human",
                "agentId": request["actor"]["id"],
                "modelId": None,
                "packetHash": packet_ref["documentHash"],
                "promptHash": None,
            },
        }
        return self._profile(packet, authoring, preserve_history=False)

    def _decision_result(
        self, event: dict, reference: dict, edited_ref=None, *, index_hash=None
    ) -> dict:
        status = (
            "needs-review"
            if edited_ref
            else "accepted"
            if event["action"] == "accept"
            else "ok"
        )
        refs = {"decision": reference, "profile": event["targetRef"]}
        if edited_ref:
            refs["proposal"] = edited_ref
        return self._result(
            "decide",
            status,
            refs=refs,
            disposition=_DISPOSITIONS[event["action"]],
            expectedIndexHash=index_hash or self.store.index_hash(),
        )

    def _edited_replay(self, event: dict) -> dict | None:
        target = self._load(event["targetRef"], "ProviderProfileVersion")
        prefix = "profile-" + content_hash("edit-" + event["requestId"]) + "-"
        state = self._index().get("profiles", {}).get(target["profileId"], {})
        return next(
            (
                ref
                for ref in state.get("revisionRefs", [])
                if ref["id"].startswith(prefix)
            ),
            None,
        )

    def _publish_decision(
        self, request: dict, profile: dict, index: dict, state: dict
    ) -> dict:
        event = seal(
            "CreatorDecision",
            {"id": self._request_identity("decision", request)[1], **request},
            clock=self.clock,
        )
        relative = f"decisions/{content_hash(_envelope_body(event))}.json"
        event = self._recover_envelope(event, relative)
        reference = document_ref(event, relative)
        documents = [(relative, event, _schema("CreatorDecision"))]
        edited_ref = None
        if request["action"] in {"edit", "qualify"}:
            edited = self._edited_profile(profile, request, reference)
            path = f"profiles/{edited['profileId']}/{edited['revisionId']}.json"
            edited_ref = document_ref(edited, path)
            documents.append((path, edited, _schema("ProviderProfileVersion")))
            state["revisionRefs"].append(edited_ref)
            state["proposedRefs"].append(edited_ref)
        state.setdefault("decisionRefs", []).append(reference)
        self._apply_pointer(request, state)
        self.store.publish(
            expected_index_hash=request["expectedIndexHash"],
            request_id=request["requestId"],
            documents=documents,
            index=index,
        )
        result = self._decision_result(event, reference, edited_ref)
        if edited_ref:
            result["warnings"] = self._view(edited)
        return result

    @staticmethod
    def _apply_pointer(request: dict, state: dict) -> None:
        if request["action"] == "accept":
            state["acceptedRef"] = request["targetRef"]
        if (
            request["action"] == "reject"
            and state.get("acceptedRef") == request["targetRef"]
        ):
            state["acceptedRef"] = None
        if request["action"] in {"accept", "reject"}:
            state["proposedRefs"] = [
                ref for ref in state["proposedRefs"] if ref != request["targetRef"]
            ]

    def decide(self, request: dict) -> dict:
        validate("ProviderDecideRequest", request)
        if request["action"] == "select":
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "Project selection cannot accept a provider profile.",
            )
        replay = self._replay("decision", request)
        if replay:
            event = self._load(replay, "CreatorDecision")
            return self._decision_result(
                event,
                replay,
                self._edited_replay(event),
                index_hash=self._request_result_hash(request["requestId"]),
            )
        if request["action"] == "accept" and (
            request.get("edits")
            or any(
                item["action"] != "accept"
                or item.get("text")
                or item.get("qualification")
                for item in request.get("statementDispositions", [])
            )
        ):
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "Changed content needs an edited proposal and a later exact acceptance.",
            )
        profile = self._load(request["targetRef"], "ProviderProfileVersion")
        _validate_dispositions(profile, request)
        index, state = self._state_for(request["targetRef"], profile)
        return self._publish_decision(request, profile, index, state)

    def _review_state(self, state: dict, reference: dict) -> str:
        if state.get("acceptedRef") == reference:
            return "accepted"
        for event_ref in reversed(state.get("decisionRefs", [])):
            event = self._load(event_ref, "CreatorDecision")
            if event["targetRef"] == reference:
                return {
                    "reject": "rejected",
                    "accept": "superseded",
                    "defer": "deferred",
                    "qualify": "qualified",
                }.get(event["action"], "proposed")
        return "proposed"

    def _profile_freshness(self, profile: dict, manifest: dict) -> dict:
        result = check_freshness(
            self.root, seal("SourceManifest", _fields(manifest), clock=self.clock)
        )
        result["affectedInputs"] = []
        try:
            self._verify_brand(profile.get("brandGuideRef"))
        except DirectionError as exc:
            result.update(status="changed", brandStatus="changed-or-unavailable")
            result["affectedInputs"].append("authored-brand")
            result["brandWarning"] = str(exc)
        return result

    def show(self, ref: str, *, check_sources=False) -> dict:
        match = re.fullmatch(r"([a-z0-9][a-z0-9._-]*)@(r\d{4,})", ref)
        if not match:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Choose an exact profileId@revisionId."
            )
        profile_id, revision = match.groups()
        relative = f"profiles/{profile_id}/{revision}.json"
        if not _contained(self.store.root, relative).is_file():
            raise DirectionError(
                "DIR_PROFILE_UNAVAILABLE",
                "Requested provider profile is unavailable; choose an existing exact profile, a built-in or none.",
                status="unavailable",
            )
        profile = self.store.load_document(relative, _schema("ProviderProfileVersion"))
        if profile["provider"] != self.provider:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Profile belongs to another provider."
            )
        reference = document_ref(profile, relative)
        _, state = self._state_for(reference, profile)
        manifest = self._manifest_content(profile["sourceManifestRef"])
        freshness = (
            self._profile_freshness(profile, manifest)
            if check_sources
            else {"status": "not-rechecked"}
        )
        return self._result(
            "show",
            refs={"profile": reference},
            profile=profile,
            reviewState=self._review_state(state, reference),
            freshness=freshness,
            coverage=manifest["coverage"],
            expectedIndexHash=self.store.index_hash(),
        )
