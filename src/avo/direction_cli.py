"""Thin command surface for provider direction and project briefing."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from importlib import resources
from pathlib import Path

from avo.direction.rules import DirectionError, validate
from avo.direction.service import DirectionService
from avo.paths import providers_dir

_STATUS_EXIT = {"invalid-request": 2, "stale": 3, "conflict": 3, "unavailable": 4}


def read_input(path, *, expected_hash=None):
    try:
        with Path(path).expanduser().open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Input exceeds 2 MiB")
        if (
            expected_hash is not None
            and hashlib.sha256(raw).hexdigest() != expected_hash
        ):
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Request content differs from the confirmed document",
                status="stale",
            )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Input must be an object")
        return value
    except (OSError, ValueError) as exc:
        if isinstance(exc, DirectionError):
            raise
        raise DirectionError(
            "DIR_INVALID_REQUEST", "Cannot read bounded JSON input"
        ) from exc


def builtin_catalog():
    raw = (
        resources.files("avo.resources.directions")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    values = json.loads(raw)["directions"]
    result = []
    for value in values:
        validate("BuiltinDirection", value)
        result.append(
            {
                "id": value["builtinId"],
                "version": value["version"],
                "title": value["title"],
                "selector": f"builtin:{value['builtinId']}@{value['version']}",
                "documentHash": value["documentHash"],
            }
        )
    return result


def _active_provider():
    from avo.avo_state import load_active_context

    return str((load_active_context() or {}).get("provider") or "")


def provider_location(slug):
    slug = slug or _active_provider()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise DirectionError("DIR_INVALID_REFERENCE", "Choose an explicit provider")
    base = providers_dir().resolve()
    path = (base / slug).resolve()
    if not path.is_relative_to(base):
        raise DirectionError("DIR_INVALID_REFERENCE", "Provider leaves its workspace")
    if not path.is_dir():
        raise DirectionError(
            "DIR_PROVIDER_UNAVAILABLE", "Provider is unavailable", status="unavailable"
        )
    return slug, path


def configure(sub):
    direction = sub.add_parser("direction", help="Review provider artistic direction")
    operations = direction.add_subparsers(dest="creative_operation", required=True)
    for name in ("catalog", "prepare", "propose", "decide", "show"):
        item = operations.add_parser(name)
        item.add_argument("--provider")
        item.add_argument("--json", action="store_true", dest="as_json")
        if name == "prepare":
            item.add_argument("--profile-id", required=True)
            item.add_argument("--entry", action="append")
            item.add_argument("--refresh-from")
        elif name in ("propose", "decide"):
            item.add_argument("--request", type=Path, required=True)
            item.add_argument(
                "--request-sha256", help="Require this exact request body digest"
            )
        elif name == "show":
            item.add_argument("--ref", required=True)
            item.add_argument("--check-sources", action="store_true")
    _configure_brief(sub)


def _configure_brief(sub):
    brief = sub.add_parser("briefstart", help="Prepare a short project direction brief")
    operations = brief.add_subparsers(dest="creative_operation", required=True)
    for name in ("prepare", "propose", "decide", "show"):
        item = operations.add_parser(name)
        item.add_argument("--project", type=Path, required=True)
        item.add_argument("--json", action="store_true", dest="as_json")
        if name == "prepare":
            item.add_argument("--direction")
            item.add_argument("--context", type=Path)
            item.add_argument("--reference", action="append", type=Path)
        elif name in ("propose", "decide"):
            item.add_argument("--request", type=Path, required=True)
            item.add_argument(
                "--request-sha256", help="Require this exact request body digest"
            )
        else:
            item.add_argument("--ref")


def _briefstart(args):
    from avo.direction.brief import BriefService

    service = BriefService(args.project)
    operation = args.creative_operation
    if operation == "prepare":
        return service.prepare(
            args.direction,
            read_input(args.context) if args.context else None,
            args.reference,
        )
    if operation in ("propose", "decide"):
        return getattr(service, operation)(
            read_input(args.request, expected_hash=args.request_sha256)
        )
    return service.show(args.ref)


def prepare_pipeline(args):
    from avo.direction.brief import BriefService

    service = BriefService(args.project)
    requested = args.direction or (service.project.get("direction") or {}).get(
        "selector", "none"
    )
    if (
        args.video_id
        and args.video_id != service.video_id
        and (requested != "none" or service.store.load_index() is not None)
    ):
        raise DirectionError(
            "DIR_INVALID_REFERENCE",
            "Artistic brief and workspace video identity differ",
        )
    return service.prepare(
        args.direction,
        read_input(args.brief_context) if args.brief_context else None,
        args.direction_reference,
    )


def _direction(args):
    if args.creative_operation == "catalog" and not (
        args.provider or _active_provider()
    ):
        return {
            "operation": "catalog",
            "status": "ok",
            "provider": None,
            "videoId": None,
            "refs": {},
            "coverage": None,
            "warnings": [],
            "nextAction": "Choose a versioned direction",
            "builtins": builtin_catalog(),
            "profiles": {},
        }
    slug, path = provider_location(args.provider)
    service = DirectionService(path, slug)
    operation = args.creative_operation
    if operation == "prepare":
        return service.prepare(
            args.profile_id, entries=args.entry, refresh_from=args.refresh_from
        )
    if operation in ("propose", "decide"):
        return getattr(service, operation)(
            read_input(args.request, expected_hash=args.request_sha256)
        )
    if operation == "show":
        return service.show(args.ref, check_sources=args.check_sources)
    return {**service.catalog(), "builtins": builtin_catalog()}


def run(args):
    try:
        result = _briefstart(args) if args.command == "briefstart" else _direction(args)
    except DirectionError as exc:
        return emit_error(exc, args.creative_operation)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return _STATUS_EXIT.get(result.get("status"), 0)


def emit_error(error, operation):
    result = {
        "operation": operation,
        "status": error.status,
        "code": error.code,
        "message": str(error),
        "details": error.details,
        "refs": {},
        "coverage": None,
        "warnings": [],
        "nextAction": "Resolve the reported request, source or index identity",
    }
    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
    return _STATUS_EXIT.get(error.status, 2)
