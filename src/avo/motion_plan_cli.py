"""Focused native craft commands shared by checkout, engine and MCP entrypoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

AUTHORING_OPERATIONS = ("plan-propose", "plan-select", "plan-apply")


def add_options_parsers(subparsers) -> None:
    from avo.editing_craft_requests import OPTIONS_OPERATIONS

    for operation in OPTIONS_OPERATIONS:
        parser = subparsers.add_parser(operation)
        parser.add_argument("--project", type=Path)
        parser.add_argument("--provider")
        parser.add_argument("--json", action="store_true", dest="as_json")
        if operation != "options-show":
            parser.add_argument("--request", type=Path, required=True)


def add_plan_parsers(subparsers) -> None:
    for operation in ("plan-show", "plan-publish", *AUTHORING_OPERATIONS):
        parser = subparsers.add_parser(operation)
        parser.add_argument("--project", type=Path, required=True)
        parser.add_argument("--video-id", default="")
        parser.add_argument("--json", action="store_true", dest="as_json")
        if operation in AUTHORING_OPERATIONS:
            parser.add_argument("--request", type=Path, required=True)
        if operation == "plan-apply":
            parser.add_argument("--request-sha256")
        if operation == "plan-show":
            parser.add_argument("--proposal-hash")


def run_craft_command(args) -> int:
    if args.animation_command in AUTHORING_OPERATIONS:
        return run_authoring_command(args)
    if args.animation_command in {"plan-show", "plan-publish"}:
        return run_plan_command(args)
    return run_options_command(args)


def run_authoring_command(args) -> int:
    from avo.editing_craft_requests import CraftRequestError, read_craft_request
    from avo.timeline.contracts import ContractError
    from avo.timeline.motion_authoring import (
        MotionAuthoringError,
        MotionAuthoringService,
    )
    from avo.timeline.workspace import TimelineWorkspace

    try:
        if not args.project.is_absolute():
            raise ValueError("Project manifest path must be absolute.")
        request = read_craft_request(
            args.request, expected_sha256=getattr(args, "request_sha256", None)
        )
        workspace = TimelineWorkspace.from_project(
            args.project, video_id=args.video_id or None
        )
        service = MotionAuthoringService(workspace)
        operation = {
            "plan-propose": service.propose,
            "plan-select": service.select,
            "plan-apply": service.apply,
        }[args.animation_command]
        result = operation(request)
    except (
        CraftRequestError,
        MotionAuthoringError,
        ContractError,
        ValueError,
        OSError,
    ) as error:
        value = (
            error.to_dict()
            if hasattr(error, "to_dict")
            else {
                "code": "MOTION_AUTHORING_INVALID",
                "message": str(error),
                "blocking": True,
            }
        )
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_plan_command(args) -> int:
    from avo.editing_craft import EditingCraftError
    from avo.timeline.contracts import ContractError
    from avo.timeline.motion_review import MotionReviewService
    from avo.timeline.pipeline import TimelinePipeline
    from avo.timeline.workspace import TimelineWorkspace

    try:
        if not args.project.is_absolute():
            raise ValueError("Project manifest path must be absolute.")
        workspace = TimelineWorkspace.from_project(
            args.project, video_id=args.video_id or None
        )
        pipeline = TimelinePipeline(workspace)
        if args.animation_command == "plan-publish":
            result = pipeline.publish_motion_plan()
            value = {**result, "effect": "derived-write"}
        else:
            snapshot = pipeline.motion_plan(
                proposal_hash=getattr(args, "proposal_hash", None)
            )
            value = {
                "snapshot": snapshot,
                "report": MotionReviewService(workspace).report_status(snapshot),
                "effect": "metadata-read",
            }
        value.update(contractVersion="1.0.0", operation=args.animation_command)
    except (EditingCraftError, ContractError, ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "code": "MOTION_REVIEW_UNAVAILABLE",
                    "message": str(error),
                    "blocking": True,
                }
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def publish_after_authoring(workspace) -> dict:
    """Keep a committed edit when publishing its required review files fails."""
    from avo.timeline.pipeline import TimelinePipeline

    try:
        return TimelinePipeline(workspace).publish_motion_plan()
    except (OSError, ValueError) as error:
        return {
            "freshness": "unavailable",
            "reviewReady": False,
            "warnings": [str(error)],
            "nextAction": "Publish the current motion plan before creator review.",
        }


def run_options_command(args) -> int:
    from avo.editing_craft import (
        EditingCraftError,
        inspect_editing_craft,
        reset_editing_craft_preference,
        set_editing_craft_preference,
    )
    from avo.editing_craft_requests import load_craft_request, options_result
    from avo.timeline.contracts import validate_document

    context = {"project": args.project, "provider": args.provider}
    try:
        if args.project is not None and not args.project.is_absolute():
            raise EditingCraftError(
                "CRAFT_PATH_INVALID",
                "Project manifest path must be absolute.",
                field="project",
            )
        request = None
        if args.animation_command == "options-show":
            result = inspect_editing_craft(**context)
        else:
            request = load_craft_request(args.request, operation=args.animation_command)
            fields = {
                "scope": request["selection"]["scope"],
                "expected_document": request["expectedDocument"],
                **context,
            }
            if args.animation_command == "options-set":
                result = set_editing_craft_preference(patch=request["patch"], **fields)
            else:
                result = reset_editing_craft_preference(**fields)
        value = options_result(result, request)
    except EditingCraftError as error:
        value = error.to_dict()
        validate_document(value, "avo.editing-craft-error.schema.json")
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0
