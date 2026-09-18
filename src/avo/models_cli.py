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


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def _cmd_show(root, as_json: bool) -> int:
    active = resolve_active_models(root)
    sources = resolve_model_sources(root)
    if as_json:
        _print_json({"activeModels": active, "resolvedModelSources": sources})
    else:
        for job, model in active.items():
            print(f"{job}: {model}")
    return 0


def _cmd_alternatives(args, root) -> int:
    alt = list_alternatives(args.job, root=root, label=args.label)
    payload = {
        "job": alt.job,
        "current": alt.current,
        "lighter": alt.lighter,
        "heavier": alt.heavier,
    }
    if args.json:
        _print_json(payload)
        return 0
    print(format_disclosure_line(alt))
    if alt.lighter:
        print("Lighter:")
        for option in alt.lighter:
            print(
                f"  - {option.get('label')} ({option.get('speed')}, {option.get('quality')})"
            )
    if alt.heavier:
        print("Heavier:")
        for option in alt.heavier:
            print(
                f"  - {option.get('label')} ({option.get('speed')}, {option.get('quality')})"
            )
    return 0


def _preflight_entry(job: str, root, label: str) -> dict:
    from avo.model_sources import PreflightError, preflight, resolve_job

    resolved = resolve_job(job, root=root, label=label)
    entry: dict = {"job": job, "id": resolved.id, "ok": True}
    try:
        preflight(resolved)
    except PreflightError as exc:
        entry["ok"] = False
        entry["code"] = exc.code
        entry["error"] = str(exc)
        if exc.hint:
            entry["hint"] = exc.hint
    return entry


def _cmd_preflight(args, root) -> int:
    from avo.model_sources import disclose_jobs

    jobs = [args.job] if args.job else ["transcribe", "understand", "plan"]
    reports = [_preflight_entry(job, root, args.label) for job in jobs]
    failed = any(not entry["ok"] for entry in reports)
    if args.json:
        _print_json(
            {
                "preflight": reports,
                "resolvedModelSources": disclose_jobs(root=root, label=args.label),
            }
        )
        return 1 if failed else 0
    for entry in reports:
        if entry["ok"]:
            print(f"{entry['job']}: ok ({entry['id']})")
        else:
            print(
                f"{entry['job']}: {entry['code']} — {entry['error']}",
                file=sys.stderr,
            )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root(args.root)
    if args.cmd == "show":
        return _cmd_show(root, args.json)
    if args.cmd == "alternatives":
        return _cmd_alternatives(args, root)
    if args.cmd == "disclosure":
        print(disclosure_summary(root))
        return 0
    if args.cmd == "preflight":
        return _cmd_preflight(args, root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
