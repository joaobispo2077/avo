"""Pure validation and identity helpers for artistic-direction documents.

These checks establish document facts, never artistic truth or human approval.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import PurePosixPath

from avo.timeline.contracts import (
    ContractError,
    content_hash,
    document_hash_excluding,
    validate_document,
)

_BRIEF_KINDS = {
    "Context",
    "ReferenceDescriptor",
    "BriefInputPacket",
    "ProjectBriefVersion",
    "BriefOptOutProposal",
    "BriefSelection",
    "ProjectBriefIndex",
    "StageGuidanceReceipt",
    "BriefPrepareRequest",
    "BriefProposeRequest",
    "BriefDecideRequest",
    "DirectionOption",
    "BriefSource",
    "FrozenBriefSource",
}
_SELECTOR = re.compile(
    r"(builtin|provider):([a-z0-9][a-z0-9._-]*)@([a-zA-Z0-9][a-zA-Z0-9.+_-]*)"
)


class DirectionError(ValueError):
    """An actionable contract, source, scope or concurrent-write failure."""

    def __init__(self, code, message, *, status="invalid-request", details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = deepcopy(details) if details is not None else {}


def parse_selector(value: str) -> dict:
    """Parse only explicit native identities; friendly names belong to the agent."""
    if value in ("none", "references"):
        return {"mode": value, "id": None, "version": None}
    match = _SELECTOR.fullmatch(value) if isinstance(value, str) else None
    if match:
        mode, identifier, version = match.groups()
        valid_version = (
            re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?", version)
            if mode == "builtin"
            else re.fullmatch(r"r\d{4,}", version)
        )
        if valid_version:
            return {"mode": mode, "id": identifier, "version": version}
    raise DirectionError(
        "DIR_INVALID_REFERENCE",
        "Choose none, references, or an exact versioned builtin/provider reference.",
    )


def visible_word_count(text: str) -> int:
    """Count the rendered short view, retaining labels and excluding link targets."""
    if not isinstance(text, str):
        raise DirectionError("DIR_INVALID_REQUEST", "Visible content must be text.")
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?m)^\s{0,3}\[[^\]\n]+\]:\s*\S+.*$", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^\n)]*\)", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"(?m)^\s*(?:```[^\n]*|~~~[^\n]*|[-*_]{3,})\s*$", "", text)
    text = re.sub(r"(?<!\w)[*_`~]+|[*_`~]+(?!\w)", "", text)
    text = re.sub(r"<((?:https?://|mailto:)[^>]+)>", r"\1", text)
    text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*)?/?>", "", text)
    return len(html.unescape(text).split())


def _schema_filename(kind, document):
    if kind in _BRIEF_KINDS:
        return "avo.briefstart.schema.json"
    if (
        kind == "CreatorDecision"
        and isinstance(document, dict)
        and document.get("scope") == "project"
    ):
        return "avo.briefstart.schema.json"
    return "avo.direction.schema.json"


def validate(kind: str, document: dict) -> None:
    """Validate a registered typed body and recompute its own identity, if stored."""
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", kind):
        raise DirectionError("DIR_INVALID_REQUEST", "Unknown direction document kind.")
    filename = _schema_filename(kind, document)
    try:
        validate_document(document, f"{filename}#/$defs/{kind}")
    except ContractError as exc:
        raise DirectionError("DIR_INVALID_REQUEST", str(exc)) from exc
    if (
        "documentType" in document
        and "documentHash" in document
        and document_hash_excluding(document, "documentHash")
        != document["documentHash"]
    ):
        raise DirectionError(
            "DIR_DOCUMENT_CHANGED",
            "Stored document content does not match its documentHash.",
            status="stale",
        )
    if (
        "indexHash" in document
        and document_hash_excluding(document, "indexHash") != document["indexHash"]
    ):
        raise DirectionError(
            "DIR_INDEX_CONFLICT",
            "Index content does not match its indexHash.",
            status="conflict",
        )


def seal(document_type: str, fields: dict, *, clock=None) -> dict:
    """Create a native immutable envelope, without manufacturing creator authority."""
    protected = {
        "createdBy",
        "createdAt",
        "documentHash",
        "documentType",
        "schemaVersion",
    }
    if not isinstance(fields, dict) or protected.intersection(fields):
        raise DirectionError(
            "DIR_INVALID_REQUEST",
            "Native envelope fields cannot be supplied as authoring content.",
        )
    timestamp = (
        clock()
        if clock
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    document = {
        "schemaVersion": "1.0.0",
        "documentType": document_type,
        "id": f"{document_type.lower()}-{content_hash(fields)[:16]}",
        "createdAt": timestamp,
        "createdBy": {"type": "native", "id": "avo.direction"},
        **deepcopy(fields),
    }
    document["documentHash"] = document_hash_excluding(document, "documentHash")
    validate(document_type, document)
    return document


def document_ref(document: dict, path: str) -> dict:
    """Return the exact stored identity, never a mutable latest alias."""
    relative = PurePosixPath(str(path).replace("\\", "/"))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not str(path)
        or ":" in str(path)
    ):
        raise DirectionError(
            "DIR_INVALID_REFERENCE",
            "Document references must remain relative to their store.",
        )
    if document_hash_excluding(document, "documentHash") != document.get(
        "documentHash"
    ):
        raise DirectionError(
            "DIR_DOCUMENT_CHANGED",
            "Cannot reference a changed document.",
            status="stale",
        )
    reference = {
        "id": document.get("id"),
        "documentHash": document["documentHash"],
        "path": relative.as_posix(),
    }
    validate("DocumentRef", reference)
    return reference


def _statement_records(statement, evidence_by_id):
    records = []
    for identifier in statement["evidenceIds"]:
        record = evidence_by_id.get(identifier)
        if record is None or record.get("evidenceId") != identifier:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Statement cites unknown evidence."
            )
        validate("EvidenceRecord", record)
        if (
            hashlib.sha256(record["excerpt"].encode("utf-8")).hexdigest()
            != record["excerptHash"]
        ):
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Evidence excerpt content has changed.",
                status="stale",
            )
        records.append(record)
    return records


def _validate_project_support(statement, records):
    known_projects = {
        record["sourceProjectId"] for record in records if record["sourceProjectId"]
    }
    if set(statement["independentProjectIds"]) != known_projects:
        raise DirectionError(
            "DIR_UNSUPPORTED_RECURRENCE",
            "Submitted project support differs from the cited records.",
        )
    if not records and statement["basis"] not in {
        "avo-default",
        "reference-suggestion",
    }:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", "A learned statement requires cited evidence."
        )


def _validate_rationale(statement, records):
    if statement["rationaleKind"] == "creator-recorded" and not any(
        record["rationaleKind"] == "creator-recorded" for record in records
    ):
        raise DirectionError(
            "DIR_APPROVAL_SCOPE",
            "Recorded creator rationale is not present in the cited evidence.",
        )


def _applicable(record, target):
    source = record.get("applicability") or {}
    return all(
        not source.get(key)
        or (target.get(key) and set(target[key]).issubset(source[key]))
        for key in ("formats", "sections", "conditions")
    )


def _validate_instruction(statement, available):
    if statement["basis"] == "creator-instruction" and not any(
        record.get("explicitInstruction")
        and record["rationaleKind"] == "creator-recorded"
        and record["normalizedState"] not in {"rejected", "superseded"}
        for record in available
    ):
        raise DirectionError(
            "DIR_APPROVAL_SCOPE",
            "A reusable creator instruction must be explicitly evidenced.",
        )


def _independent_actual_projects(available):
    eligible = [
        record
        for record in available
        if record["sourceProjectId"]
        and record.get("useEvidence")
        and record["normalizedState"] in {"executed", "observed", "approved"}
    ]
    lineage_projects = {}
    for record in eligible:
        lineage_projects.setdefault(record["decisionLineageId"], set()).add(
            record["sourceProjectId"]
        )
    independent = (
        set().union(
            *(projects for projects in lineage_projects.values() if len(projects) == 1)
        )
        if lineage_projects
        else set()
    )
    return independent


def _validate_exclusions(statement, records):
    retained = set(statement["exclusions"]) | set(
        statement["applicability"].get("exclusions", [])
    )
    required = {
        exclusion
        for record in records
        for exclusion in record.get("applicability", {}).get("exclusions", [])
    }
    if not required.issubset(retained):
        raise DirectionError(
            "DIR_APPROVAL_SCOPE",
            "Statement must retain its supporting sources' applicability exclusions.",
        )


def validate_statement(statement: dict, evidence_by_id: dict) -> None:
    """Check attributable support without asserting semantic entailment."""
    validate("DirectionStatement", statement)
    records = _statement_records(statement, evidence_by_id)
    _validate_project_support(statement, records)
    _validate_rationale(statement, records)
    available = [
        record for record in records if _applicable(record, statement["applicability"])
    ]
    if records and not available:
        raise DirectionError(
            "DIR_APPROVAL_SCOPE", "Statement applicability exceeds its source context."
        )
    _validate_instruction(statement, available)
    _validate_exclusions(statement, available)
    if (
        statement["basis"] == "recurring-choice"
        and len(_independent_actual_projects(available)) < 2
    ):
        raise DirectionError(
            "DIR_UNSUPPORTED_RECURRENCE",
            "Recurrence requires applicable actual use in two independent source projects.",
        )


def _options_view(options, short_view="", singleton_reason=""):
    """The exact short presentation generated for an options proposal."""
    lines = [short_view.strip()]
    for option in options:
        lines.extend([f"### {option['id']}", option["approach"]])
        lines.extend(
            f"{key}: {value}"
            for key, value in option["treatment"].items()
            if isinstance(value, str)
        )
        lines.extend(option["treatment"].get("sectionVariants", []))
        lines.extend(
            [f"Fit: {option['fit']}", "Trade-offs: " + "; ".join(option["tradeoffs"])]
        )
        lines.extend(
            f"Source {source['sourceId']}: {'; '.join(source['aspects'])}"
            for source in option["sourceContribution"]
        )
        lines.append("Exclusions: " + "; ".join(option["exclusions"]))
    if singleton_reason:
        lines.append("One viable direction: " + singleton_reason)
    return "\n\n".join(line for line in lines if line)


def _validate_option_structure(options, singleton_reason):
    if not isinstance(options, list) or not 1 <= len(options) <= 3:
        raise DirectionError(
            "BRIEF_INVALID_OPTIONS",
            "Provide two or three options, or one justified option.",
        )
    for option in options:
        validate("DirectionOption", option)
    if len(options) == 1 and not singleton_reason.strip():
        raise DirectionError(
            "BRIEF_INVALID_OPTIONS",
            "A singleton direction requires a constraint explanation.",
        )
    if len({option["id"] for option in options}) != len(options):
        raise DirectionError(
            "BRIEF_INVALID_OPTIONS", "Option identities must be distinct."
        )
    treatments = {content_hash(option["treatment"]) for option in options}
    if len(treatments) != len(options):
        raise DirectionError(
            "BRIEF_INVALID_OPTIONS",
            "Different names alone do not establish different treatments.",
        )


def validate_options(
    options: list, short_view: str, singleton_reason: str = ""
) -> None:
    """Validate comparable options and the complete native-rendered reading budget."""
    _validate_option_structure(options, singleton_reason)
    if visible_word_count(_options_view(options, short_view, singleton_reason)) > 600:
        raise DirectionError(
            "BRIEF_WORD_LIMIT", "The complete visible briefing exceeds 600 words."
        )
