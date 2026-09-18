"""CLI for model catalog transparency."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from avo.models import (
    disclosure_summary,
    format_disclosure_line,
    list_alternatives,
    repo_root,
    resolve_active_models,
    resolve_model_sources,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AVO model catalog — show active models and alternatives"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="Show active models for all jobs")
    p_show.add_argument("--root", type=Path, default=None)
    p_show.add_argument("--json", action="store_true")

    p_alt = sub.add_parser(
        "alternatives", help="List lighter/heavier options for one job"
    )
    p_alt.add_argument("job", choices=["transcribe", "understand", "plan"])
    p_alt.add_argument("--label", default="local", choices=["local", "paid"])
    p_alt.add_argument("--root", type=Path, default=None)
    p_alt.add_argument("--json", action="store_true")

    sub.add_parser("disclosure", help="Setup-style disclosure block")

    p_pre = sub.add_parser("preflight", help="Fail-closed source/runtime check")
    p_pre.add_argument(
        "job",
        nargs="?",
        choices=["transcribe", "understand", "plan"],
        default=None,
    )
    p_pre.add_argument("--label", default="local", choices=["local", "paid"])
    p_pre.add_argument("--root", type=Path, default=None)
    p_pre.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root(args.root)

    if args.cmd == "show":
        active = resolve_active_models(root)
        sources = resolve_model_sources(root)
        if args.json:
            print(
                json.dumps(
                    {"activeModels": active, "resolvedModelSources": sources},
                    indent=2,
                )
            )
        else:
            for job, model in active.items():
                print(f"{job}: {model}")
        return 0

    if args.cmd == "alternatives":
        alt = list_alternatives(args.job, root=root, label=args.label)
        payload = {
            "job": alt.job,
            "current": alt.current,
            "lighter": alt.lighter,
            "heavier": alt.heavier,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(format_disclosure_line(alt))
            if alt.lighter:
                print("Lighter:")
                for o in alt.lighter:
                    print(
                        f"  - {o.get('label')} ({o.get('speed')}, {o.get('quality')})"
                    )
            if alt.heavier:
                print("Heavier:")
                for o in alt.heavier:
                    print(
                        f"  - {o.get('label')} ({o.get('speed')}, {o.get('quality')})"
                    )
        return 0

    if args.cmd == "disclosure":
        print(disclosure_summary(root))
        return 0

    if args.cmd == "preflight":
        from avo.model_sources import (
            PreflightError,
            disclose_jobs,
            preflight,
            resolve_job,
        )

        jobs = [args.job] if args.job else ["transcribe", "understand", "plan"]
        reports = []
        failed = False
        for job in jobs:
            resolved = resolve_job(job, root=root, label=args.label)
            entry = {"job": job, "id": resolved.id, "ok": True}
            try:
                preflight(resolved)
            except PreflightError as exc:
                failed = True
                entry["ok"] = False
                entry["code"] = exc.code
                entry["error"] = str(exc)
                if exc.hint:
                    entry["hint"] = exc.hint
            reports.append(entry)
        if args.json:
            print(
                json.dumps(
                    {
                        "preflight": reports,
                        "resolvedModelSources": disclose_jobs(
                            root=root, label=args.label
                        ),
                    },
                    indent=2,
                )
            )
        else:
            for entry in reports:
                if entry["ok"]:
                    print(f"{entry['job']}: ok ({entry['id']})")
                else:
                    print(
                        f"{entry['job']}: {entry['code']} — {entry['error']}",
                        file=sys.stderr,
                    )
        return 1 if failed else 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
