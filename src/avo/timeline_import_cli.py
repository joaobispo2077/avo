"""Local OTIO import command entry point with explicit dependency boundaries."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from avo.timeline.otio_import import MAX_REPORT_BYTES, ImportError, inspect_export


def configure(subparsers):
    group = subparsers.add_parser("timeline-import")
    commands = group.add_subparsers(dest="import_command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--input", type=Path, required=True)
    inspect.add_argument("--timeline")
    inspect.add_argument("--project", type=Path)
    inspect.add_argument("--json", action="store_true", dest="as_json")
    for name in ("prepare", "validate", "activate", "status", "rollback"):
        parser = commands.add_parser(name)
        parser.add_argument("--project", type=Path, required=True)
        parser.add_argument("--provider")
        parser.add_argument("--json", action="store_true", dest="as_json")
        if name == "rollback":
            _configure_return(parser)
            continue
        if name != "prepare":
            parser.add_argument("--import-id", required=name != "status")
        if name in {"prepare", "activate"}:
            parser.add_argument("--actor", required=True)
            parser.add_argument("--reason", required=True)
        if name == "prepare":
            parser.add_argument("--input", type=Path, required=True)
            parser.add_argument("--timeline")
            parser.add_argument("--media-root", type=Path, action="append")
            parser.add_argument("--supersedes-import-id")
            parser.add_argument("--mappings", type=Path)
            parser.add_argument("--declarations", type=Path)
        if name == "activate":
            parser.add_argument("--validation-hash", required=True)
            parser.add_argument("--expected-head", required=True)


def _configure_return(parser):
    for flag in ("--activation-id", "--expected-head", "--actor", "--reason"):
        parser.add_argument(flag, required=True)


def _inspect(args):
    result = inspect_export(args.input, timeline=args.timeline)
    if args.project:
        try:
            project = json.loads(args.project.read_text(encoding="utf-8"))
            result["target"] = {
                "provider": project["provider"],
                "projectPath": str(args.project),
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ImportError(
                "OTIO_INPUT_INVALID", "Cannot read declared project context"
            ) from exc
    return result


def create_service(args):
    from avo.adapters.media.ffprobe import FfprobeMediaAdapter
    from avo.adapters.media.otio_reader import read_otio
    from avo.adapters.media.still_probe import verify_literal_still
    from avo.timeline.import_service import TimelineImportService

    return TimelineImportService(
        args.project,
        provider=getattr(args, "provider", None),
        reader=read_otio,
        probe=FfprobeMediaAdapter().inventory,
        still_probe=verify_literal_still,
    )


def _options_document(path):
    from avo.timeline.import_service import _document

    if path is None:
        return None
    try:
        value = _document(path)
        if not isinstance(value, dict):
            raise ValueError("Import option documents must contain an object")
        return value
    except ImportError:
        raise
    except (OSError, ValueError) as exc:
        raise ImportError(
            "OTIO_INPUT_INVALID",
            "Cannot read the local import option document",
            scope=str(path),
        ) from exc


def dispatch(args, service):
    if args.import_command == "rollback":
        return service.rollback(
            args.activation_id,
            expected_head=args.expected_head,
            actor=args.actor,
            reason=args.reason,
        )
    if args.import_command == "prepare":
        return service.prepare(
            args.input,
            timeline=args.timeline,
            media_roots=args.media_root,
            mappings=_options_document(args.mappings),
            declarations=_options_document(args.declarations),
            supersedes_import_id=args.supersedes_import_id,
            actor=args.actor,
            reason=args.reason,
        )
    if args.import_command == "validate":
        return service.validate(args.import_id)
    if args.import_command == "activate":
        return service.activate(
            args.import_id,
            validation_hash=args.validation_hash,
            expected_head=args.expected_head,
            actor=args.actor,
            reason=args.reason,
        )
    return service.status(args.import_id)


def _encode_report(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _finding_counts(result):
    findings = result.get("findings", [])
    return result.get("summary", {}).get("findingCounts") or {
        "total": len(findings),
        **dict(Counter(row["code"] for row in findings)),
    }


def _display_findings(findings):
    selected = {}
    for finding in findings:
        key = (finding["code"], finding.get("scope", ""))
        if key in selected:
            selected[key]["blocking"] |= finding.get("blocking", False)
            continue
        row = deepcopy(finding)
        for name in ("message", "remediation"):
            if name in row:
                row[name] = row[name][:512]
        selected[key] = row
    return list(selected.values())


def _omit_accounted_elements(result):
    result["elements"] = []
    for container in (
        result.get("summary", {}),
        result.get("validation", {}).get("locks", {}),
    ):
        accounting = container.get("elementAccounting")
        if accounting is not None:
            accounting.update(reported=0, truncated=True)


def _display_fields(document, fields):
    return {key: document[key] for key in fields if key in document}


def _compact_documents(result):
    fields = {
        "session": (
            "schemaVersion",
            "normalizerVersion",
            "importId",
            "provider",
            "videoId",
            "state",
            "source",
            "refs",
            "expectedHeadHash",
            "createdAt",
            "supersedesImportId",
        ),
        "proposal": ("schemaVersion", "importId", "output"),
        "validation": ("schemaVersion", "importId", "state", "locks", "ready"),
        "revision": (
            "revisionId",
            "parentRevisionId",
            "createdAt",
            "contentHash",
            "state",
        ),
        "activation": (
            "schemaVersion",
            "operationId",
            "importId",
            "phase",
            "expectedHeadHash",
            "validationHash",
            "revisionId",
            "previousRevisionId",
            "revisionHash",
            "createdAt",
        ),
    }
    for key, retained in fields.items():
        if key in result:
            result[key] = _display_fields(result[key], retained)


def _compact_report(result):
    compact = deepcopy(
        _display_fields(
            result,
            (
                "schemaVersion",
                "operation",
                "status",
                "capabilityLevel",
                "importId",
                "validationHash",
                "source",
                "target",
                "session",
                "readiness",
                "summary",
                "proposal",
                "validation",
                "revision",
                "activation",
                "currentOrigin",
                "currentCanonical",
                "pipelineAction",
                "active",
                "nextAction",
                "findings",
                "findingCounts",
                "name",
                "schemas",
            ),
        )
    )
    compact["truncated"] = True
    compact["findingCounts"] = _finding_counts(result)
    _omit_accounted_elements(compact)
    _compact_documents(compact)
    compact["findings"] = _display_findings(compact.get("findings", []))
    return compact


def _bound_findings(result):
    findings = result["findings"]
    result["findings"] = []
    result["findingsTruncated"] = True
    # Reserve the newline written by print and every encoded list separator.
    remaining = MAX_REPORT_BYTES - len(_encode_report(result).encode("utf-8")) - 1
    for row in findings:
        size = len(_encode_report(row).encode("utf-8"))
        separator = 2 if result["findings"] else 0
        if size + separator > remaining:
            continue
        result["findings"].append(row)
        remaining -= size + separator


def _report_json(result):
    encoded = _encode_report(result)
    if len(encoded.encode("utf-8")) + 1 <= MAX_REPORT_BYTES:
        return encoded
    compact = _compact_report(result)
    encoded = _encode_report(compact)
    if len(encoded.encode("utf-8")) + 1 > MAX_REPORT_BYTES:
        _bound_findings(compact)
        encoded = _encode_report(compact)
    return encoded


def run(args):
    result = (
        _inspect(args)
        if args.import_command == "inspect"
        else dispatch(args, create_service(args))
    )
    print(_report_json(result))
    return (
        3
        if result["status"]
        in {"blocked", "awaiting-sync", "recovery-required", "stale"}
        else 0
    )
