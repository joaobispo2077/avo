"""CLI entrypoint for AVO job adapters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from helpers.adapters.base import AdapterError, JobRequest, repo_root, resolve_adapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an AVO job through the port/adapter layer")
    parser.add_argument("job", help="Job id from avo.config.json (e.g. transcribe)")
    parser.add_argument(
        "--label",
        default="local",
        choices=["local", "paid"],
        help="Routing label (local or paid)",
    )
    parser.add_argument("--root", type=Path, default=None, help="Repo root override")
    parser.add_argument(
        "adapter_argv",
        nargs=argparse.REMAINDER,
        help="Arguments after -- forwarded to the adapter",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root(args.root)
    adapter_argv = args.adapter_argv
    if adapter_argv and adapter_argv[0] == "--":
        adapter_argv = adapter_argv[1:]
    request = JobRequest(job=args.job, label=args.label, argv=adapter_argv, root=root)
    try:
        adapter = resolve_adapter(args.job, args.label, root)
        result = adapter.run(request)
    except AdapterError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.exit_code == 0:
        payload = {
            "job": args.job,
            "label": args.label,
            "adapter": getattr(adapter, "routing_id", "unknown"),
            "artifacts": [str(p) for p in result.artifact_paths],
        }
        if result.models_used:
            payload["modelsUsed"] = result.models_used
        print(json.dumps(payload))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
