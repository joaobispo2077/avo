"""Executable batch workflow for parameter-driven YouTube Shorts."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from avo import shorts_contract, shorts_delivery, shorts_media, shorts_plan, shorts_qc
from avo.adapters.motion.hyperframes import (
    HyperframesAdapter,
    build_composition_spec,
    compile_project,
)

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_TRANSCRIPT_REQUIRED = 3
EXIT_APPROVAL_REQUIRED = 4
EXIT_NOT_IMPLEMENTED = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m avo.shorts")
    subparsers = parser.add_subparsers(dest="action", required=True)

    validate = subparsers.add_parser("validate", help="validate a batch request")
    validate.add_argument("request", type=Path)

    resolve = subparsers.add_parser("resolve", help="resolve an immutable plan")
    resolve.add_argument("request", type=Path)
    resolve.add_argument("-o", "--output", type=Path, required=True)

    build = subparsers.add_parser("build", help="build proofs or masters")
    build.add_argument("plan", type=Path)
    build.add_argument("--stage", choices=("proof", "master"), required=True)
    build.add_argument("--short", action="append", dest="short_ids")
    build.add_argument("--workers", type=int, default=2)
    build.add_argument("--preview", action="store_true", help="render proofs at 640x360 for cheap review")
    build.add_argument("--approval-manifest", type=Path)
    build.add_argument("--delivery-dir", type=Path)
    qc = subparsers.add_parser("qc", help="evaluate proof or master artifacts")
    qc.add_argument("plan", type=Path)
    qc.add_argument("--stage", choices=("proof", "master"), required=True)
    qc.add_argument("--short", action="append", dest="short_ids")
    status = subparsers.add_parser("status", help="show read-only batch status")
    status.add_argument("plan", type=Path)
    promote = subparsers.add_parser("promote", help="promote approved proofs")
    promote.add_argument("plan", type=Path)
    promote.add_argument("--approval-manifest", type=Path, required=True)
    promote.add_argument("--delivery-dir", type=Path)
    return parser


def _validate(args: argparse.Namespace) -> int:
    request = shorts_plan.validate_request_file(args.request)
    transcript = request["source"].get("transcriptPath")
    if transcript:
        print(f"valid request: {args.request} (transcript: {transcript})")
    else:
        print(
            f"valid request: {args.request} "
            "(transcript will be created before resolution)"
        )
    return EXIT_OK


def _resolve(args: argparse.Namespace) -> int:
    output = shorts_plan.resolve_request_file(args.request, args.output)
    print(f"resolved plan: {output}")
    return EXIT_OK


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_path(plan_path: Path) -> Path:
    return plan_path.with_name("shorts.status.json")


def _new_status(plan: Mapping[str, Any], plan_path: Path) -> dict[str, Any]:
    approval = plan.get("planApproval") or {}
    approved = approval.get("status") == "approved" and approval.get("reference")
    return {
        "version": "1.0", "batchId": plan["batchId"],
        "planPath": str(plan_path), "planHash": plan["planHash"],
        "batchState": "plan-approved" if approved else "plan-pending",
        "updatedAt": _now(),
        "items": [{
            "shortId": item["id"], "inputFingerprint": item["inputFingerprint"],
            "state": "pending", "dirty": True, "dirtyReasons": ["new-short"],
            "proofRevision": 0, "masterRevision": 0, "artifacts": [], "errors": [],
        } for item in plan["items"]],
        "batchApprovals": ([{
            "gate": "batch-plan", "status": "approved",
            "reference": approval["reference"],
            "timestamp": approval.get("timestamp"),
        }] if approved else []),
        "blockingRisks": [], "batchQcSummary": None, "deliveryComplete": False,
    }


def _artifact(kind: str, path: Path, revision: int) -> dict[str, Any]:
    return {
        "kind": kind, "path": str(path),
        "hash": shorts_media.sha256_file(path), "revision": revision,
    }


def _build_one_proof(
    plan: Mapping[str, Any], item: Mapping[str, Any], plan_path: Path,
    prior: Mapping[str, Any], *,
    prepare: Callable[..., Mapping[str, shorts_media.PreparedAsset]],
    adapter_factory: Callable[[], HyperframesAdapter],
    preview: bool = False,
) -> dict[str, Any]:
    revision = int(prior.get("proofRevision", 0)) + 1
    batch_root = plan_path.parent / "shorts" / plan["batchId"]
    revision_name = f"proof-v{revision:03d}"
    work = batch_root / str(item["id"]) / revision_name
    if work.exists():
        raise RuntimeError(f"immutable proof revision already exists: {work}")
    request_path = Path(plan["requestPath"])
    request = shorts_contract.load_document(request_path, "request")
    output = dict(plan["output"])
    if preview:
        output = {
            **output,
            "width": 640,
            "height": 360,
            "preview": True,
        }
    master_value = Path(request["source"]["masterPath"])
    master = master_value.resolve() if master_value.is_absolute() else (request_path.parent / master_value).resolve()
    crop_mode = str(item["layout"].get("cropMode") or request["defaults"]["layout"].get("cropMode") or "cover")
    prepared = prepare(
        master, work / "prepared",
        start_sec=item["sourceRange"]["startSec"], end_sec=item["sourceRange"]["endSec"],
        speed=item["speed"], fps=output["fps"],
        width=output["width"], height=output["height"],
        sample_rate=output.get("audioSampleRateHz", 48000),
        channels=output.get("audioChannels", 2),
        crop_mode=crop_mode,
    )
    if item.get("insertion"):
        policy = next(
            insertion for insertion in request.get("insertions") or []
            if insertion["id"] == item["insertion"]["id"]
        )
        insertion_value = Path(policy["sourcePath"])
        insertion_source = insertion_value.resolve() if insertion_value.is_absolute() else (request_path.parent / insertion_value).resolve()
        shorts_media.validate_insertion_source(insertion_source, policy)
        insertion_assets, _source_map = shorts_media.prepare_insertion_assets(
            insertion_source, work / "prepared-insertion",
            approved_windows=policy["approvedWindows"],
            excluded_windows=policy.get("excludedWindows") or [],
            target_duration=item["editedDurationSec"],
            video_stream=item["insertion"]["videoStreamIndex"],
            audio_stream=item["insertion"].get("audioStreamIndex"),
            support_volume=item["insertion"]["supportVolume"],
            fps=plan["output"]["fps"],
        )
        prepared = {**prepared, **insertion_assets}
    assets = {key: value.as_contract() for key, value in prepared.items()}
    expected = work / "renders" / f"{item['expectedOutputBasename']}-proof-v{revision:03d}.mp4"
    spec = build_composition_spec(
        batch_id=plan["batchId"], item=item, output=output, assets=assets,
        proof_revision=revision, expected_output_path=expected,
        provider_tokens=plan.get("providerTokens"),
    )
    project = compile_project(spec, work / "hyperframes")
    adapter = adapter_factory()
    checked = adapter.execute("check", project, "--snapshots", root=Path.cwd())
    if checked.exit_code:
        raise RuntimeError(checked.stderr or checked.stdout or "HyperFrames strict check failed")
    contact_sheet = work / "qc" / "contact-sheet.jpg"
    try:
        shorts_qc.generate_contact_sheet(project, contact_sheet)
    except ValueError:
        contact_sheet = None
    rendered = adapter.execute("render", project, "--output", str(expected), root=Path.cwd())
    if rendered.exit_code:
        raise RuntimeError(rendered.stderr or rendered.stdout or "HyperFrames render failed")
    if not expected.is_file():
        candidates = [path for path in rendered.artifact_paths if path.suffix.lower() == ".mp4"]
        if candidates:
            expected = candidates[-1]
        else:
            raise RuntimeError("HyperFrames completed without an MP4 proof")
    artifacts = [
        _artifact("prepared-base", prepared["baseVideo"].path, revision),
        _artifact("prepared-dialogue", prepared["dialogueAudio"].path, revision),
        _artifact("composition", project / "composition.json", revision),
        _artifact("proof", expected, revision),
    ]
    if contact_sheet and contact_sheet.is_file():
        artifacts.append(_artifact("contact-sheet", contact_sheet, revision))
    if "insertionVideo" in prepared:
        artifacts.insert(2, _artifact("prepared-insertion-video", prepared["insertionVideo"].path, revision))
    if "insertionAudio" in prepared:
        artifacts.insert(3, _artifact("prepared-insertion-audio", prepared["insertionAudio"].path, revision))
    render_profile = shorts_plan.target_render_profile(plan, preview=preview)
    return {
        **dict(prior), "shortId": item["id"],
        "inputFingerprint": item["inputFingerprint"], "state": "proof-ready",
        "dirty": False, "dirtyReasons": [], "proofRevision": revision,
        "renderProfile": render_profile,
        "artifacts": [*(prior.get("artifacts") or []), *artifacts], "errors": [],
        "hyperframesValidation": {"status": "passed", "strict": True},
    }


def build_proofs(
    plan_path: Path,
    *,
    short_ids: Sequence[str] | None = None,
    workers: int = 2,
    preview: bool = False,
    prepare: Callable[..., Mapping[str, shorts_media.PreparedAsset]] = shorts_media.prepare_base_assets,
    adapter_factory: Callable[[], HyperframesAdapter] = HyperframesAdapter,
) -> tuple[Path, dict[str, Any]]:
    plan_path = plan_path.resolve()
    plan = shorts_contract.load_document(plan_path, "plan")
    shorts_contract.require_plan_approval(plan)
    status_path = _status_path(plan_path)
    status = shorts_contract.load_document(status_path, "status") if status_path.exists() else _new_status(plan, plan_path)
    if status.get("planHash") != plan["planHash"]:
        status = _new_status(plan, plan_path)
    wanted = set(short_ids or [item["id"] for item in plan["items"]])
    unknown = wanted - {item["id"] for item in plan["items"]}
    if unknown:
        raise shorts_contract.ContractValidationError(f"unknown Short IDs: {', '.join(sorted(unknown))}")
    dirty = shorts_plan.dirty_items(plan, status, preview=preview)
    item_status = {item["shortId"]: item for item in status["items"]}
    pending = [item for item in plan["items"] if item["id"] in wanted and item["id"] in dirty]
    status["batchState"] = "building-proofs"
    status["updatedAt"] = _now()
    shorts_contract.atomic_write_json(status_path, status)
    futures = {}
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 4))) as pool:
        for item in pending:
            prior = item_status[item["id"]]
            prior["state"] = "preparing"
            prior["dirtyReasons"] = dirty[item["id"]]
            futures[pool.submit(
                _build_one_proof, plan, item, plan_path, prior,
                prepare=prepare, adapter_factory=adapter_factory, preview=preview,
            )] = item["id"]
        for future in as_completed(futures):
            short_id = futures[future]
            try:
                item_status[short_id] = future.result()
            except Exception as exc:
                prior = item_status[short_id]
                item_status[short_id] = {
                    **prior, "state": "failed", "dirty": True,
                    "errors": [*(prior.get("errors") or []), str(exc)],
                }
            status["items"] = [item_status[item["id"]] for item in plan["items"]]
            status["updatedAt"] = _now()
            shorts_contract.atomic_write_json(status_path, status)
    failures = [item for item in status["items"] if item["state"] == "failed"]
    status["batchState"] = "proof-partial" if failures else "proofs-ready"
    status["updatedAt"] = _now()
    shorts_contract.validate_document(status, "status")
    shorts_contract.atomic_write_json(status_path, status)
    return status_path, status


def _build(args: argparse.Namespace) -> int:
    plan = shorts_contract.load_document(args.plan.resolve(), "plan")
    try:
        shorts_contract.require_plan_approval(plan)
    except shorts_contract.ContractValidationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_APPROVAL_REQUIRED
    if args.stage == "master":
        if not args.approval_manifest:
            print("--approval-manifest is required for master promotion", file=sys.stderr)
            return EXIT_APPROVAL_REQUIRED
        return _promote(args)
    status_path, status = build_proofs(
        args.plan, short_ids=args.short_ids, workers=args.workers, preview=args.preview,
    )
    failures = [item["shortId"] for item in status["items"] if item["state"] == "failed"]
    print(f"proof status: {status_path}")
    if failures:
        print(f"proof failures: {', '.join(failures)}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_OK


def _qc(args: argparse.Namespace) -> int:
    plan_path = args.plan.resolve()
    plan = shorts_contract.load_document(plan_path, "plan")
    status_path = _status_path(plan_path)
    status = shorts_contract.load_document(status_path, "status")
    selected = set(args.short_ids or [item["id"] for item in plan["items"]])
    plan_items = {item["id"]: item for item in plan["items"]}
    failed = []
    passed = []
    for item_status in status["items"]:
        if item_status["shortId"] not in selected:
            continue
        kind = "proof" if args.stage == "proof" else "master"
        artifact = next((a for a in reversed(item_status["artifacts"]) if a["kind"] == kind), None)
        plan_item = plan_items[item_status["shortId"]]
        output = plan["output"]
        if artifact is None:
            item_status["qc"] = {"status": "failed", "findings": [{"severity": "error", "code": f"missing-{kind}"}]}
        else:
            item_status["qc"] = shorts_qc.qc_proof_artifact(
                plan_item, artifact,
                watch_reference=item_status.get("watchReviewReference"),
                output=output,
            )
        if item_status["qc"]["status"] == "passed":
            item_status["state"] = "proof-approved" if args.stage == "proof" else "master-qc"
            passed.append(item_status["shortId"])
        else:
            failed.append(item_status["shortId"])
    status["batchQcSummary"] = {
        "stage": args.stage,
        "passed": len(passed),
        "failed": len(failed),
        "selected": len(selected),
        "updatedAt": _now(),
    }
    status["batchState"] = "proof-review" if args.stage == "proof" else "master-qc"
    status["updatedAt"] = _now()
    shorts_contract.atomic_write_json(status_path, status)
    print(json.dumps({"statusPath": str(status_path), "failed": failed}, indent=2))
    return EXIT_INVALID if failed else EXIT_OK


def _status(args: argparse.Namespace) -> int:
    path = _status_path(args.plan.resolve())
    status = shorts_contract.load_document(path, "status")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return EXIT_OK


def _promote(args: argparse.Namespace) -> int:
    plan_path = args.plan.resolve()
    plan = shorts_contract.load_document(plan_path, "plan")
    status_path = _status_path(plan_path)
    status = shorts_contract.load_document(status_path, "status")
    approvals = json.loads(args.approval_manifest.read_text(encoding="utf-8"))
    shorts_contract.validate_promotion_evidence(status, approvals)
    status["batchApprovals"] = approvals["approvals"]
    for review in approvals.get("watchReviews") or []:
        match = next(item for item in status["items"] if item["shortId"] == review["shortId"])
        match["watchReviewReference"] = review["reference"]
        match["watchReview"] = {
            key: review[key]
            for key in (
                "reference", "candidateHash", "candidateIdentityHash",
                "dependencyLockSha256", "evidenceBundleSha256", "proofRevision",
            )
        }
    delivery_dir = (args.delivery_dir or plan_path.parent / "delivery" / plan["batchId"]).resolve()
    result = shorts_delivery.promote_batch(plan, status, delivery_dir)
    result["status"]["updatedAt"] = _now()
    shorts_contract.validate_document(result["status"], "status")
    shorts_contract.atomic_write_json(status_path, result["status"])
    print(f"delivery manifest: {result['manifestPath']}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.action == "validate":
            return _validate(args)
        if args.action == "resolve":
            return _resolve(args)
        if args.action == "build":
            return _build(args)
        if args.action == "qc":
            return _qc(args)
        if args.action == "status":
            return _status(args)
        if args.action == "promote":
            return _promote(args)
    except shorts_plan.TranscriptRequiredError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_TRANSCRIPT_REQUIRED
    except (shorts_contract.ContractValidationError, shorts_delivery.DeliveryError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID
    return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
