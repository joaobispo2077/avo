"""Native commands for explicitly selected editor interchange evidence."""

import json
import sys
from pathlib import Path
from subprocess import SubprocessError


def configure(subparsers):
    parent = subparsers.add_parser("timeline-export")
    subcommands = parent.add_subparsers(dest="export_command", required=True)
    for operation in (
        "prepare",
        "status",
        "inspect-feedback",
        "propose-feedback",
        "apply-feedback",
        "qualify-target",
    ):
        parser = subcommands.add_parser(operation)
        parser.add_argument("--project", type=Path, required=True)
        parser.add_argument("--video-id", default="")
        parser.add_argument("--request", type=Path, required=operation != "status")
        parser.add_argument("--request-sha256")
        parser.add_argument("--json", action="store_true", dest="as_json")


def run(args):
    from avo.adapters.registry import build_cutting_service, build_editor_handoff
    from avo.editing_craft_requests import read_craft_request
    from avo.timeline.command_registry import authorize
    from avo.timeline.editor_feedback_service import (
        apply_feedback,
        inspect_feedback,
        propose_feedback,
    )
    from avo.timeline.editor_qualification import qualify_target
    from avo.timeline.workspace import TimelineWorkspace

    try:
        authorize("exports")
        if not args.project.is_absolute():
            raise ValueError("Project manifest path must be absolute")
        request = (
            read_craft_request(args.request, expected_sha256=args.request_sha256)
            if args.request
            else {"contractVersion": "1.0.0", "operation": "status"}
        )
        if request.get("operation") != args.export_command:
            raise ValueError(
                "Editor export request differs from the selected operation"
            )
        workspace = TimelineWorkspace.from_project(
            args.project, video_id=args.video_id or None
        )
        service = build_editor_handoff(workspace)
        result = {
            "prepare": lambda: service.prepare(request),
            "status": lambda: service.status(request),
            "inspect-feedback": lambda: inspect_feedback(service, request),
            "propose-feedback": lambda: propose_feedback(service, request),
            "apply-feedback": lambda: apply_feedback(
                service,
                request,
                cutting_factory=lambda: build_cutting_service(workspace),
            ),
            "qualify-target": lambda: qualify_target(service, request),
        }[args.export_command]()
    except (OSError, ValueError, RuntimeError, SubprocessError) as error:
        print(
            json.dumps(
                {"status": "blocked", "message": str(error)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
