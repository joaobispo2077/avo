"""CLI entrypoint for AVO job adapters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from avo.adapters.base import AdapterError, JobRequest, resolve_adapter
from avo.motion import MotionError
from avo.paths import repo_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an AVO job through the port/adapter layer"
    )
    parser.add_argument("job", help="Job id from avo.config.json (e.g. transcribe)")
    parser.add_argument(
        "--label",
        default="local",
        choices=["local", "paid"],
        help="Routing label (local or paid)",
    )
    parser.add_argument("--root", type=Path, default=None, help="Repo root override")
    parser.add_argument(
        "--motion-engine",
        choices=["hyperframes", "remotion", "code-drawn"],
        help="One-invocation motion engine override",
    )
    parser.add_argument("--project", type=Path, help="Motion project file or directory")
    parser.add_argument("--provider", help="Motion provider/channel id")
    return parser


def _emit_result(args, adapter, result) -> int:
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.exit_code != 0:
        return result.exit_code
    payload = {
        "job": args.job,
        "label": args.label,
        "adapter": getattr(adapter, "routing_id", "unknown"),
        "artifacts": [str(p) for p in result.artifact_paths],
    }
    if result.models_used:
        payload["modelsUsed"] = result.models_used
    if result.model_sources:
        payload["resolvedModelSources"] = result.model_sources
    print(json.dumps(payload))
    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    boundary = values.index("--") if "--" in values else len(values)
    args = build_parser().parse_args(values[:boundary])
    adapter_argv = values[boundary + 1 :] if boundary < len(values) else []
    root = repo_root(args.root)
    request = JobRequest(job=args.job, label=args.label, argv=adapter_argv, root=root)
    try:
        adapter = resolve_adapter(
            args.job,
            args.label,
            root,
            motion_engine=args.motion_engine,
            project=args.project,
            provider=args.provider,
        )
        result = adapter.run(request)
    except MotionError as exc:
        print(json.dumps(exc.to_dict()), file=sys.stderr)
        return 2
    except AdapterError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _emit_result(args, adapter, result)


if __name__ == "__main__":
    sys.exit(main())
