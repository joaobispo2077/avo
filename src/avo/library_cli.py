"""Thin shared native command boundary for the footage library."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from avo.library.rules import LibraryError, read_request, reject
from avo.library.service import LibraryService


def configure(sub):
    parser = sub.add_parser(
        "organize", help="Review and organize a local footage library"
    )
    operations = parser.add_subparsers(dest="library_operation", required=True)
    for name in (
        "scan",
        "propose",
        "review",
        "prepare",
        "approve",
        "apply",
        "status",
        "resume",
        "reverse",
        "search",
        "select",
        "cancel",
    ):
        item = operations.add_parser(name)
        common(item)
        item.add_argument("--recursive", action="store_true")
        item.add_argument("--request", type=Path)
        item.add_argument("--request-sha256")
        item.add_argument("--selection", type=Path)
        item.add_argument("--proposal")
        item.add_argument("--approval")
        item.add_argument("--operation")
        item.add_argument("--query")
        item.add_argument(
            "--mode", choices=("metadata", "speech", "all"), default="all"
        )
        item.add_argument("--limit", type=int, default=20)
        item.add_argument("--cursor")
        item.add_argument(
            "--transcript",
            action="append",
            default=[],
            help="Admit an existing transcript as RECORDING_ID=ROOT_RELATIVE_PATH",
        )
        for key in ("group", "date-from", "date-to", "transcript-status"):
            item.add_argument("--" + key)
        item.add_argument("--min-duration", type=float)
        item.add_argument("--max-duration", type=float)
    batch = operations.add_parser("batch")
    children = batch.add_subparsers(dest="library_batch_operation", required=True)
    for name in ("prepare", "run"):
        item = children.add_parser(name)
        common(item)
        item.add_argument("--request", type=Path)
        item.add_argument("--request-sha256")
        item.add_argument("--approval")


def common(parser):
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")


def dispatch(service, args):
    _arguments(args)
    handlers = {
        "scan": lambda: _scan(service, args),
        "propose": lambda: service.propose(_request(args) if args.request else None),
        "review": lambda: _review(service, args),
        "search": lambda: _search(service, args),
        "select": lambda: service.select(_request(args)),
        "prepare": lambda: service.prepare(args.proposal, read_request(args.selection)),
        "approve": lambda: service.approve(_request(args)),
        "apply": lambda: service.apply(args.approval),
        "resume": lambda: service.resume(args.operation),
        "reverse": lambda: service.reverse(args.operation),
        "cancel": lambda: _cancel(service, args.operation),
        "status": lambda: service.status(args.operation),
        "batch": lambda: _batch(service, args),
    }
    handler = handlers.get(args.library_operation)
    if handler is None:
        reject(
            "LIB_CAPABILITY_UNAVAILABLE", "Operation is not available", "unavailable"
        )
    return handler()


def _arguments(args):
    required = {
        "review": ("proposal",),
        "prepare": ("proposal", "selection"),
        "apply": ("approval",),
        "resume": ("operation",),
        "reverse": ("operation",),
        "cancel": ("operation",),
        "search": ("query",),
    }
    if args.library_operation == "batch":
        fields = (
            ("approval",)
            if args.library_batch_operation == "run"
            else ("request", "request_sha256")
        )
    else:
        fields = required.get(args.library_operation, ())
    missing = [
        "--" + field.replace("_", "-")
        for field in fields
        if not getattr(args, field, None)
    ]
    if missing:
        reject("LIB_INVALID_REQUEST", "Supply " + ", ".join(missing))


def _batch(service, args):
    if args.library_batch_operation == "prepare":
        return service.prepare_batch(_request(args))
    return service.run_batch(args.approval)


def _request(args):
    if not args.request or not args.request_sha256:
        reject(
            "LIB_INVALID_REQUEST", "Supply the reviewed request and its exact SHA-256"
        )
    return read_request(args.request, args.request_sha256)


def _scan(service, args):
    result = service.scan(recursive=args.recursive)
    for item in args.transcript:
        if "=" not in item:
            reject("LIB_INVALID_REQUEST", "Use RECORDING_ID=TRANSCRIPT_PATH")
        result = service.admit_transcript(*item.split("=", 1))
    return result


def _review(service, args):
    service.writable()
    head = service.store.head()
    ref, proposal = service.store.lookup("proposal", args.proposal)
    return service._review_result({**head, "proposalRef": ref}, proposal)


def _search(service, args):
    fields = {
        "group": "group",
        "date_from": "dateFrom",
        "date_to": "dateTo",
        "transcript_status": "transcriptStatus",
        "min_duration": "minDuration",
        "max_duration": "maxDuration",
    }
    filters = {
        target: getattr(args, key)
        for key, target in fields.items()
        if getattr(args, key) is not None
    }
    return service.search(
        args.query,
        mode=args.mode,
        limit=args.limit,
        cursor=args.cursor,
        filters=filters,
    )


def _cancel(service, operation_id):
    service.writable()
    return service.store.cancel(operation_id)


def _with_progress(service, args):
    from avo.library.progress import Progress

    if args.library_operation in {"status", "cancel"}:
        return dispatch(service, args)
    with Progress(
        service.store,
        args.library_operation,
        observe_resources=args.library_operation != "search",
    ) as progress:
        service.progress = progress
        if service.store.head_path.exists():
            progress.library_id = service.store.head()["libraryId"]
        telemetry = _phase_telemetry(service, args, "start", 1)
        try:
            result = dispatch(service, args)
        except (LibraryError, OSError) as exc:
            _failure_report(service, progress, exc)
            raise
        if args.library_operation != "search":
            counts = {
                **result.get("summary", {}),
                "createdBytes": service.store.created_bytes
                + result.get("summary", {}).get("createdBytes", 0),
            }
            ref = progress.finish(
                status=result.get("status", "ok"),
                estimates=result.get("estimates"),
                counts=counts,
                usage=result.get("usage"),
            )
            result.setdefault("refs", {})["report"] = ref
            result["performance"] = service.store.get(ref)
        else:
            result["elapsedSeconds"] = progress._clock() - progress._started
        if telemetry:
            result["telemetry"] = _phase_telemetry(service, args, "complete", 2)
        return result


def _phase_telemetry(service, args, stage, index):
    if args.library_operation == "search":
        return None
    from avo.telemetry import Telemetry

    try:
        record = Telemetry(volume=service.root, total_phases=2).report(
            f"library-{args.library_operation}-{stage}",
            index=index,
            total=2,
            created_bytes=service.store.created_bytes if stage == "complete" else 0,
            active_models={},
            model_sources={},
            emit=False,
        )
        print("AVO_JSON " + json.dumps(record, ensure_ascii=True), file=sys.stderr)
        return record
    except OSError:
        return {
            "coverage": "unavailable",
            "reason": "Global telemetry could not be persisted",
        }


def _emit_result(result, as_json):
    encoded = json.dumps(result, ensure_ascii=True)
    if as_json:
        print(encoded)
        return
    print(f"Library {result['operation']}: {result['status']}")
    summary = result.get("summary", {})
    print(" | ".join(f"{key}: {value}" for key, value in summary.items()))
    review = result.get("refs", {}).get("review", {})
    for name, path in review.items():
        print(f"Review {name}: {path}")
    report = result.get("performance")
    if report:
        print(
            f"Elapsed: {report['elapsedSeconds']:.2f}s | created bytes: {report['resources']['createdBytes']} | usage: {report['usage']['coverage']}"
        )
    print("AVO_JSON " + encoded, file=sys.stderr)


def _failure_report(service, progress, error):
    try:
        service.writable()
        cancelled = getattr(error, "status", None) == "cancelled"
        error.library_report = progress.finish(
            status="cancelled" if cancelled else "failed",
            counts={
                "createdBytes": service.store.created_bytes,
                "failed": int(not cancelled),
            },
        )
    except (LibraryError, OSError):
        return


def run(args):
    print(
        "AVO_JSON "
        + json.dumps(
            {
                "phase": "starting",
                "operation": args.library_operation,
                "total": None,
                "estimatedSeconds": None,
            }
        ),
        file=sys.stderr,
    )
    try:
        from avo.adapters.media.ffprobe import library_metadata

        service = LibraryService(args.root, args.provider, probe=library_metadata)
        result = _with_progress(service, args)
        result = {
            "schemaVersion": 1,
            "operation": args.library_operation,
            "root": str(service.root),
            "provider": service.provider,
            **result,
        }
        _emit_result(result, args.as_json)
        return {"partial": 1, "cancelled": 130, "blocked": 3}.get(
            result.get("status"), 0
        )
    except (LibraryError, OSError) as exc:
        status = getattr(exc, "status", "failed")
        print(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "operation": args.library_operation,
                    "status": status,
                    "code": getattr(exc, "code", "LIB_IO_ERROR"),
                    "message": str(exc),
                    "refs": {"report": getattr(exc, "library_report", None)},
                    "nextAction": "Resolve the reported library boundary and retry",
                }
            )
        )
        return {
            "invalid-request": 2,
            "stale": 3,
            "conflict": 3,
            "unavailable": 4,
            "cancelled": 130,
        }.get(status, 1)
