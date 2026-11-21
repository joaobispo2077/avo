"""Explicit local SFX catalogue operations shared by CLI and MCP."""

from __future__ import annotations

import json
import sys
from argparse import SUPPRESS
from dataclasses import replace
from pathlib import Path

OPERATIONS = (
    "show",
    "scan",
    "annotate",
    "search",
    "search-semantic",
    "propose",
    "apply",
    "favorites-show",
    "favorite-promote",
    "favorite-remove",
)


def configure(subparsers):
    parser = subparsers.add_parser("sfx")
    operations = parser.add_subparsers(dest="sfx_command", required=True)
    for operation in OPERATIONS:
        item = operations.add_parser(operation)
        item.add_argument("--project", type=Path, required=True)
        item.add_argument("--video-id", default="")
        item.add_argument("--json", action="store_true", dest="as_json")
        if operation == "show":
            item.add_argument("--generation")
            item.add_argument("--offset", type=int, default=0)
            item.add_argument("--limit", type=int, default=20)
        elif operation != "favorites-show":
            item.add_argument("--request", type=Path, required=True)
        if operation in {"apply", "favorite-promote", "favorite-remove"}:
            item.add_argument("--request-sha256", help=SUPPRESS)


def resolve_sfx_roots(workspace, *, root=None):
    """Reuse asset scope resolution; an empty project asset inherits its provider."""
    from avo.video_context import VideoContext, merge_config

    project = workspace.project
    context = VideoContext(
        provider=str(project.get("provider") or ""),
        video_id=workspace.video_id,
        raw_dir=workspace.raw_dir,
        video_key=None,
        project=project,
    )
    # Asset manifests define empty values as inheritance, not disabling a library.
    assets = {
        key: value for key, value in (project.get("assets") or {}).items() if value
    }
    config = merge_config(
        replace(context, project={**project, "assets": assets}), root=root
    )
    value = (config.get("assets") or {}).get("sfx")
    if not value:
        return {}
    return {"sfx": _local_library(value)}


def _local_library(value):
    if (
        not isinstance(value, str)
        or "://" in value
        or value.startswith(("\\\\", "//"))
        or not Path(value).is_absolute()
    ):
        raise ValueError("Sound library must use a local absolute path.")
    return Path(value).expanduser()


def _request(path, operation, *, expected_sha256=None):
    from avo.editing_craft_requests import read_craft_request
    from avo.timeline.contracts import validate_document

    value = read_craft_request(path, expected_sha256=expected_sha256)
    definitions = {"propose": "proposeRequest", "apply": "applyRequest"}
    schema = (
        "avo.sound-selection.schema.json#/$defs/" + definitions[operation]
        if operation in definitions
        else "avo.sfx-request.schema.json"
    )
    if operation in {"favorite-promote", "favorite-remove"}:
        schema = "avo.sfx-provider.schema.json#/$defs/request"
    validate_document(value, schema)
    if value["operation"] != operation:
        raise ValueError("Sound request operation does not match the selected command.")
    return value


def _excerpt(document, *, offset=0, limit=20):
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 100
    ):
        raise ValueError(
            "Catalogue offset must be nonnegative and limit must be 1..100."
        )
    entries = document["entries"]
    end = min(len(entries), offset + limit)
    return {
        **document,
        "entries": entries[offset:end],
        "scanCoverage": document["coverage"],
        "coverage": {
            "shown": len(entries[offset:end]),
            "total": len(entries),
            "offset": offset,
        },
        "nextOffset": end if end < len(entries) else None,
    }


def _execute(service, args, request):
    operation = args.sfx_command
    if operation in {"favorites-show", "favorite-promote", "favorite-remove"}:
        from avo.sfx_preferences import (
            inspect_sfx_favorites,
            promote_sfx_favorite,
            remove_sfx_favorite,
        )

        if operation == "favorite-promote":
            return promote_sfx_favorite(service, request)
        if operation == "favorite-remove":
            return remove_sfx_favorite(service.workspace, request)
        return inspect_sfx_favorites(service.workspace)
    if operation in {"propose", "apply"}:
        from avo.timeline.sound_planning import SoundPlanningService

        probe = None
        if operation == "apply":
            from avo.adapters.registry import build_sound_source_probe

            probe = build_sound_source_probe()
        planning = SoundPlanningService(
            service.workspace, catalogue=service, source_probe=probe
        )
        return getattr(planning, operation)(request)
    if operation == "show":
        return _excerpt(
            service.show(args.generation), offset=args.offset, limit=args.limit
        )
    if operation == "scan":
        return _excerpt(
            service.scan(
                expected_generation=request["expectedGeneration"],
                actor=request["actor"],
                reason=request["reason"],
                budget=request.get("budget"),
                resume=request.get("resume"),
            )
        )
    if operation == "annotate":
        return _excerpt(
            service.annotate(
                request["selection"]["entryId"],
                request["patch"],
                expected_generation=request["expectedGeneration"],
                actor=request["actor"],
                reason=request["reason"],
            )
        )
    return service.search(
        request["query"],
        filters=request.get("filters"),
        limit=request.get("limit", 20),
        cursor=request.get("cursor"),
        generation=request.get("generation"),
        mode="semantic" if operation == "search-semantic" else "descriptor",
    )


def _catalogue(workspace, operation, request):
    from avo.adapters.registry import build_sfx_catalog

    roots = (
        {}
        if operation in {"favorites-show", "favorite-promote", "favorite-remove"}
        else resolve_sfx_roots(workspace)
    )
    preferences = {}
    if operation == "scan" and request.get("useProviderFavorites", False):
        from avo.sfx_preferences import inspect_sfx_favorites

        preferences["favorites"] = inspect_sfx_favorites(workspace)
    return build_sfx_catalog(
        workspace,
        roots=roots,
        analyze=operation == "scan",
        semantic=operation == "search-semantic",
        **preferences,
    )


def run(args):
    from avo.timeline.command_registry import CommandPermissionError
    from avo.timeline.workspace import TimelineWorkspace

    try:
        if not args.project.is_absolute():
            raise ValueError("Project manifest path must be absolute.")
        request = (
            None
            if args.sfx_command in {"show", "favorites-show"}
            else _request(
                args.request,
                args.sfx_command,
                expected_sha256=getattr(args, "request_sha256", None),
            )
        )
        workspace = TimelineWorkspace.from_project(
            args.project, video_id=args.video_id or None
        )
        service = _catalogue(workspace, args.sfx_command, request)
        result = _execute(service, args, request)
        if result.get("generationId"):
            result["catalogueRef"] = {
                "path": str(
                    service.directory
                    / "generations"
                    / (result["generationId"] + ".json")
                ),
                "generationId": result["generationId"],
            }
    except (ValueError, OSError, CommandPermissionError) as error:
        value = (
            error.to_dict()
            if hasattr(error, "to_dict")
            else {
                "code": "SFX_REQUEST_INVALID",
                "message": str(error),
                "blocking": True,
                "remediation": "Inspect the selected catalogue generation, declared sound root and request.",
            }
        )
        print(
            json.dumps(value),
            file=sys.stderr,
        )
        return 2
    effect = {
        "scan": "source-analysis",
        "annotate": "metadata-write",
        "propose": "metadata-write",
        "apply": "canonical-write",
        "search-semantic": "model-execution",
        "favorites-show": "metadata-read",
        "favorite-promote": "provider-metadata-write",
        "favorite-remove": "provider-metadata-write",
    }.get(args.sfx_command, "metadata-read")
    result.update(contractVersion="1.0.0", operation=args.sfx_command, effect=effect)
    if request:
        result["operationId"] = request["operationId"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
