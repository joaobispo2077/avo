"""Local cost commands shared by installed runtime, CLI and MCP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from avo.cost_store import CostError, CostStore, read_json
from avo.costs import render_summary, summarize

STRUCTURED_REQUESTS = {
    "context": ("descriptor", "context"),
    "observe": ("packet", "packet"),
    "transition": ("request", "transition"),
    "estimate": ("request", "estimate-request"),
    "reconcile": ("reconciliation", "reconcile-request"),
    "report-manual": ("request", "manual-request"),
}
_REQUEST_FILES = {
    "context": "descriptor",
    "observe": "file",
    "transition": "request",
    "estimate": "request",
    "reconcile": "file",
}


def configure(sub):
    parser = sub.add_parser(
        "costs", aliases=["metrics"], help="Recorded video tokens and cost"
    )
    _options(parser)
    operations = parser.add_subparsers(dest="cost_operation")
    for name in (
        "report",
        "capabilities",
        "bind",
        "collect",
        "import",
        "report-manual",
        "snapshot",
        "price",
        "correct",
        "close-binding",
        "fork",
        "revalue",
        "context",
        "observe",
        "transition",
        "estimate",
        "reconcile",
    ):
        item = operations.add_parser(name)
        _options(item, inherit=True)
        _operation_arguments(item, name)


def _metadata_arguments(item, name):
    inputs = item.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--" + _REQUEST_FILES[name], type=Path)
    inputs.add_argument("--payload-json", help=argparse.SUPPRESS)


def _operation_arguments(item, name):
    if name in _REQUEST_FILES:
        _metadata_arguments(item, name)
    if name in {"import", "price", "correct", "revalue"}:
        item.add_argument("--file", type=Path, required=True)
    if name == "report-manual":
        inputs = item.add_mutually_exclusive_group(required=True)
        inputs.add_argument("--file", type=Path)
        inputs.add_argument("--payload-json", help=argparse.SUPPRESS)
        item.add_argument("--participation-fact-id")
        item.add_argument("--operation-id")
    if name == "bind":
        item.add_argument("--source", type=Path, required=True)
        item.add_argument("--boundary", required=True)
        item.add_argument("--run-id")
    if name in {"bind", "import"}:
        item.add_argument("--session-id")
        item.add_argument("--format", default="normalized")
    if name == "snapshot":
        item.add_argument(
            "--stage", choices=("draft", "final", "amendment"), default="draft"
        )
    if name in {"collect", "close-binding"}:
        item.add_argument("--binding-id")
    if name == "close-binding":
        item.add_argument("--end-boundary", required=True)
    if name == "fork":
        item.add_argument("--new-video-id", required=True)
    item.add_argument("--agent")


def _options(parser, *, inherit=False):
    default = argparse.SUPPRESS if inherit else None
    flag_default = argparse.SUPPRESS if inherit else False
    parser.add_argument("--project", type=Path, default=default)
    for name in ("video-id", "provider", "phase", "snapshot-id"):
        parser.add_argument(f"--{name}", default=default)
    parser.add_argument("--history", action="store_true", default=flag_default)
    parser.add_argument("--trends", action="store_true", default=flag_default)
    parser.add_argument(
        "--json", action="store_true", dest="as_json", default=flag_default
    )


def _workspace(args):
    from avo.timeline.workspace import TimelineWorkspace

    path = args.project
    if path is None and (Path.cwd() / "avo.project.json").is_file():
        path = Path.cwd() / "avo.project.json"
    if path is None:
        raise CostError("choose --project explicitly; no unambiguous video context")
    workspace = TimelineWorkspace.from_project(path)
    if args.video_id and args.video_id != workspace.video_id:
        raise CostError("video selector differs from the selected project")
    if args.provider and args.provider != workspace.project.get("provider"):
        raise CostError("provider selector differs from the selected project")
    return workspace


def _run(args):
    from avo.cost_sources import capabilities

    operation = args.cost_operation
    if operation in _REQUEST_FILES:
        args.cost_payload = _request_payload(args)
    if operation == "report-manual":
        args.manual_request = _manual_payload(args)
    if operation == "capabilities":
        return {
            "agents": [
                v for v in capabilities() if not args.agent or v["agent"] == args.agent
            ]
        }
    if args.history or args.trends:
        return _history(args)
    workspace = _workspace(args)
    return _project_operation(args, workspace)


def _project_operation(args, workspace):
    operation = args.cost_operation
    store = CostStore(workspace.raw_dir)
    if operation in {None, "report"}:
        if args.snapshot_id:
            return _read_snapshot(store, args.snapshot_id)
        return summarize(store, phase=args.phase)
    store.initialize(
        str(workspace.project.get("provider") or "unknown"), workspace.video_id
    )
    from avo.cost_history import remember

    remember(store)
    return _mutate(store, workspace, args)


def _history(args):
    from avo.cost_history import history, trends

    selected = CostStore(_workspace(args).raw_dir) if args.project else None
    result = history(provider=args.provider, video_id=args.video_id, store=selected)
    if args.trends:
        result["trends"] = trends(result)
    return result


def _read_snapshot(store, snapshot_id):
    import re

    if not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
        raise CostError("invalid snapshot identity")
    value = store.read_snapshot(snapshot_id)
    if value["accountingVideoId"] != store.identity()["accountingVideoId"]:
        raise CostError("snapshot belongs to another video")
    return value


def _mutate(store, workspace, args):
    from avo.cost_sources import collect

    handlers = {
        "import": lambda: _import_rows(store, args),
        "report-manual": lambda: _import_rows(store, args),
        "bind": lambda: _bind(store, args),
        "collect": lambda: collect(store, binding_id=args.binding_id),
        "close-binding": lambda: store.close_binding(
            args.binding_id, args.end_boundary
        ),
        "price": lambda: {"priceScheduleId": store.price(read_json(args.file))},
        "correct": lambda: _correct(store, read_json(args.file)),
        "fork": lambda: _fork(store, args.new_video_id),
        "revalue": lambda: _revalue(store, read_json(args.file)),
        "snapshot": lambda: _snapshot(store, workspace, args.stage),
        "context": lambda: _register_context(store, args.cost_payload),
        "observe": lambda: _observe(store, args.cost_payload),
        "transition": lambda: _transition(store, args.cost_payload),
        "estimate": lambda: _estimate(store, args.cost_payload),
        "reconcile": lambda: _reconcile(store, args.cost_payload),
    }
    return handlers[args.cost_operation]()


def _request_payload(args):
    from avo.cost_participation import validate_context_descriptor
    from avo.cost_store import validate

    if args.payload_json is not None:
        payload = json.loads(args.payload_json)
    else:
        field = _REQUEST_FILES[args.cost_operation]
        payload = read_json(getattr(args, field))
    if args.cost_operation == "context":
        return validate_context_descriptor(payload)
    if args.cost_operation == "estimate":
        from avo.cost_estimates import validate_estimate_request

        validate_estimate_request(payload)
        return payload
    validate(STRUCTURED_REQUESTS[args.cost_operation][1], payload)
    return payload


def _register_context(store, payload):
    from avo.cost_participation import register_context

    return register_context(store, payload)


def _observe(store, payload):
    return {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        **store.ingest_packet(payload),
    }


def _transition(store, payload):
    from avo.cost_participation import transition_context

    return transition_context(store, payload)


def _estimate(store, payload):
    from avo.cost_estimates import create_estimate

    return create_estimate(store, payload)


def _reconcile(store, payload):
    from avo.cost_participation import reconcile_costs

    return reconcile_costs(store, payload)


def cost_context_argument(value):
    """Argparse adapter never echoes an invalid metadata payload."""
    from avo.cost_participation import validate_context_descriptor

    try:
        return validate_context_descriptor(json.loads(value))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "invalid cost context; supply v2 metadata only"
        ) from exc


def _manual_payload(args):
    from avo.cost_sources import import_file
    from avo.cost_store import validate

    fact_id, operation_id = args.participation_fact_id, args.operation_id
    if args.payload_json is not None:
        if fact_id is not None or operation_id is not None:
            raise CostError("choose structured manual metadata or file flags")
        payload = json.loads(args.payload_json)
    elif fact_id is not None or operation_id is not None:
        if not fact_id or not operation_id:
            raise CostError(
                "manual usage requires both participation fact and operation ID"
            )
        if args.file.stat().st_size > 32 * 1024 * 1024:
            raise CostError("manual usage source exceeds 32 MiB")
        payload = {
            "schemaVersion": "2.0.0",
            "operationId": operation_id,
            "participationFactId": fact_id,
            "observations": import_file(args.file, "normalized"),
        }
    else:
        return None
    validate("manual-request", payload)
    return payload


def _import_rows(store, args):
    from avo.cost_sources import import_file

    if getattr(args, "manual_request", None) is not None:
        from avo.cost_sources import report_manual

        payload = args.manual_request
        return report_manual(
            store,
            payload["observations"],
            participation_fact_id=payload["participationFactId"],
            operation_id=payload["operationId"],
        )
    rows = import_file(
        args.file,
        getattr(args, "format", "normalized"),
        session_id=getattr(args, "session_id", None),
    )
    if args.cost_operation == "report-manual":
        rows = [{**r, "measurementKind": "manual"} for r in rows]
    return store.ingest(rows)


def _bind(store, args):
    if not args.agent or not args.session_id:
        raise CostError("bind requires --agent and --session-id")
    return store.bind(
        source=args.source,
        agent=args.agent,
        session_id=args.session_id,
        boundary=args.boundary,
        source_format=args.format,
        run_id=args.run_id,
        phase=args.phase,
    )


def _correct(store, value):
    result = store.correct(
        value["observationId"],
        value["action"],
        value["actor"],
        value["reason"],
        selected=value.get("selected"),
    )
    store.amend_if_closed()
    return result


def _fork(store, video_id):
    from avo.cost_history import remember
    from avo.cost_store import validate

    identity = store.identity()
    validate("identity", {**identity, "videoId": video_id})
    archived = store.raw_dir / "edit/cost-ancestors" / identity["accountingVideoId"]
    if (
        not archived.resolve().is_relative_to(store.raw_dir)
        or archived.parent.resolve() != archived.parent.absolute()
    ):
        raise CostError("fork archive leaves the project or contains a link")
    if archived.exists():
        raise CostError("fork archive already exists; resolve identity explicitly")
    archived.parent.mkdir(parents=True, exist_ok=True)
    store.root.rename(archived)
    remember(CostStore(archived, archive=True))
    return store.initialize(identity["provider"], video_id)


def _snapshot(store, workspace, stage):
    closure = _cleanup_evidence(workspace.raw_dir) if stage == "final" else None
    return store.snapshot(summarize(store), stage, closure=closure)


def _revalue(store, price):
    from avo.costs import _estimate

    price_id = store.price(price)
    rows, _ = store.observations()
    updated = 0
    for row in rows:
        amount = _estimate(row, [price])
        if not amount:
            continue
        original_id = row.pop("observationId")
        row = {k: v for k, v in row.items() if not k.startswith("_")}
        row["amounts"] = amount
        store.ingest([row])
        store.correct(
            original_id,
            "select",
            "costs.revalue",
            "explicit historical revaluation",
            selected=store.digest(row),
        )
        updated += 1
    store.amend_if_closed()
    return {
        "priceScheduleId": price_id,
        "revalued": updated,
        "basis": "explicit revaluation; historical snapshots retained",
    }


def _cleanup_evidence(raw_dir):
    path = Path(raw_dir) / "edit/cleanup/cleanup-result.json"
    if not path.is_file():
        raise CostError("final snapshot requires a completed cleanup result")
    value = read_json(path)
    if value.get("status") != "completed":
        raise CostError("final snapshot requires completed cleanup evidence")
    return {
        "receiptPath": "edit/cleanup/cleanup-result.json",
        "receiptHash": CostStore.digest(value),
    }


def run(args):
    try:
        result = _run(args)
    except (CostError, ValueError, KeyError, TypeError) as exc:
        message = (
            str(exc)
            if isinstance(exc, CostError)
            else "invalid cost input; check documented fields"
        )
        print(
            json.dumps({"status": "invalid-input", "message": message}), file=sys.stderr
        )
        return 2
    except OSError:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "message": "Cost source/storage unavailable; existing evidence retained",
                }
            ),
            file=sys.stderr,
        )
        return 1
    if not args.as_json and "videos" in result:
        _print_history(result)
    elif args.as_json or "tokens" not in result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_summary(result))
        _print_breakdowns(result)
    return 0


def _print_history(result):
    if not result["videos"]:
        print(result["message"])
    for video in result["videos"]:
        label = f"{video.get('provider')}/{video.get('videoId')}"
        label = json.dumps(label, ensure_ascii=True)[1:-1]
        print(f"{label}: {render_summary(video)}")
    for cohort in result.get("trends", []):
        print(
            f"Recorded cohort: {cohort['sampleSize']} videos, {cohort['unit']} {cohort['basis']}, mean {cohort['meanPerVideo'] or 'insufficient evidence'}; {cohort['limitations']}"
        )


def _print_breakdowns(report):
    for dimension in ("model", "serviceProvider", "phase"):
        for name, value in report.get("breakdowns", {}).get(dimension, {}).items():
            label = json.dumps(name, ensure_ascii=True)
            print(
                f"{dimension} {label}: {value['tokens'].get('total')} recorded tokens; {json.dumps(value['amounts'])}"
            )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="avo")
    sub = parser.add_subparsers(dest="command", required=True)
    configure(sub)
    return run(parser.parse_args(["costs", *(argv or sys.argv[1:])]))
