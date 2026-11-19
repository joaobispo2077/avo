"""Explicit source evidence inspection and bounded local speech recovery."""

import json
import sys
from argparse import SUPPRESS
from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser("preparation")
    operations = parser.add_subparsers(dest="preparation_command", required=True)
    for operation in ("coverage", "recover", "recover-decide"):
        item = operations.add_parser(operation)
        item.add_argument("--project", type=Path, required=True)
        item.add_argument("--video-id", default="")
        item.add_argument("--request", type=Path, required=True)
        item.add_argument("--json", action="store_true", dest="as_json")
        if operation != "coverage":
            item.add_argument("--request-sha256", help=SUPPRESS)


def run(args):
    from avo.adapters.registry import build_preparation_service
    from avo.editing_craft_requests import read_craft_request
    from avo.timeline.workspace import TimelineWorkspace

    try:
        if not args.project.is_absolute():
            raise ValueError("Project manifest path must be absolute")
        request = read_craft_request(
            args.request, expected_sha256=getattr(args, "request_sha256", None)
        )
        if not isinstance(request, dict):
            raise ValueError("Preparation request must be an object")
        from avo.timeline.contracts import validate_document

        definition = {
            "coverage": "coverageRequest",
            "recover": "recoverRequest",
            "recover-decide": "decideRequest",
        }[args.preparation_command]
        validate_document(request, "avo.preparation.schema.json#/$defs/" + definition)
        if request.get("operation") != args.preparation_command:
            raise ValueError(
                "Request operation differs from selected preparation command"
            )
        workspace = TimelineWorkspace.from_project(
            args.project, video_id=args.video_id or None
        )
        service = build_preparation_service(
            workspace,
            recover=args.preparation_command == "recover"
            or request.get("choice") == "recovered",
        )
        operation = (
            "decide"
            if args.preparation_command == "recover-decide"
            else args.preparation_command
        )
        result = getattr(service, operation)(request)
    except (OSError, ValueError) as error:
        print(
            json.dumps({"status": "invalid-input", "message": str(error)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
