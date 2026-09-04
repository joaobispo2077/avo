"""Executable batch workflow for parameter-driven YouTube Shorts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avo import (
    shorts_contract,
    shorts_delivery,
    shorts_media,
    shorts_paths,
    shorts_plan,
    shorts_qc,
)
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


def _apply_loudness_preset(
    input_path: Path, output_path: Path, *, preset_id: str, preview: bool
) -> bool:
    """Apply the shared AVO loudness engine without slowing normal Shorts imports."""
    from avo import loudness_profiles, render

    profile = loudness_profiles.resolve_loudness_profile(preset_override=preset_id)
    return render.apply_loudnorm_two_pass(
        input_path,
        output_path,
        preview=preview,
        profile=profile,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m avo.shorts")
    subparsers = parser.add_subparsers(dest="action", required=True)

    validate = subparsers.add_parser("validate", help="validate a batch request")
    validate.add_argument("request", type=Path)
    _add_batch_root_arguments(validate)

    resolve = subparsers.add_parser("resolve", help="resolve an immutable plan")
    resolve.add_argument("request", type=Path)
    resolve.add_argument("-o", "--output", type=Path)
    _add_batch_root_arguments(resolve)

    build = subparsers.add_parser("build", help="build proofs or masters")
    build.add_argument("plan", type=Path)
    build.add_argument("--stage", choices=("proof", "master"), required=True)
    build.add_argument("--short", action="append", dest="short_ids")
    build.add_argument("--workers", type=int, default=2)
    build.add_argument(
        "--preview",
        action="store_true",
        help="render proofs at 640x360 for cheap review",
    )
    build.add_argument("--approval-manifest", type=Path)
    build.add_argument("--delivery-dir", type=Path)
    _add_batch_root_arguments(build)
    qc = subparsers.add_parser("qc", help="evaluate proof or master artifacts")
    qc.add_argument("plan", type=Path)
    qc.add_argument("--stage", choices=("proof", "master"), required=True)
    qc.add_argument("--short", action="append", dest="short_ids")
    _add_batch_root_arguments(qc)
    status = subparsers.add_parser("status", help="show read-only batch status")
    status.add_argument("plan", type=Path)
    _add_batch_root_arguments(status)
    promote = subparsers.add_parser("promote", help="promote approved proofs")
    promote.add_argument("plan", type=Path)
    promote.add_argument("--approval-manifest", type=Path, required=True)
    promote.add_argument("--delivery-dir", type=Path)
    _add_batch_root_arguments(promote)
    return parser


def _add_batch_root_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--raw-dir",
        type=Path,
        help="footage-project root that owns edit/shorts",
    )
    parser.add_argument(
        "--batch-dir",
        type=Path,
        help="supported nested batch root under <rawDir>/edit/shorts",
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise shorts_contract.ContractValidationError(
            f"expected a JSON object: {path.resolve()}"
        )
    return payload


def _raw_dir_from_batch_root(batch_root: Path | str) -> Path | None:
    cursor = Path(batch_root).expanduser().resolve()
    for parent in (cursor, *cursor.parents):
        if parent.name == "shorts" and parent.parent.name == "edit":
            return parent.parent.parent
    return None


def _request_paths(
    request_path: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], shorts_paths.ShortsBatchPaths | None]:
    request = _read_json_object(request_path)
    version = str(request.get("version") or "1.0")
    raw_dir = _request_raw_dir(request, args)
    if raw_dir is None and version == "1.1":
        raise shorts_paths.ShortsPathError(
            "v1.1 Shorts requests require --raw-dir (and optional --batch-dir) "
            "so the canonical batch root can be resolved before work"
        )
    if raw_dir is None:
        return request, None
    raw_dir = Path(raw_dir).expanduser().resolve()
    batch_dir = _request_batch_dir(request, args, raw_dir)
    paths = shorts_paths.resolve_shorts_batch_paths(
        raw_dir,
        str(request.get("batchId") or ""),
        batch_dir=batch_dir,
    )
    _normalize_request_media_paths(request, request_path.parent)
    if version == "1.1":
        request["batchRoot"] = str(paths.batch_root)
        request["batchRootSource"] = paths.root_source
    shorts_contract.validate_document(request, "request")
    shorts_paths.register_batch(paths)
    return request, paths


def _request_raw_dir(
    request: Mapping[str, Any], args: argparse.Namespace
) -> Path | None:
    if args.raw_dir is not None:
        return args.raw_dir
    if request.get("batchRoot"):
        return _raw_dir_from_batch_root(request["batchRoot"])
    return None


def _request_batch_dir(
    request: Mapping[str, Any], args: argparse.Namespace, raw_dir: Path
) -> Path | str | None:
    if args.batch_dir is not None:
        return args.batch_dir
    declared = request.get("batchRoot")
    if not declared:
        return None
    declared_path = Path(declared).expanduser()
    default = raw_dir / "edit" / "shorts" / str(request.get("batchId") or "")
    if declared_path.is_absolute():
        return None if declared_path.resolve() == default.resolve() else declared
    return (
        None if declared_path == Path(str(request.get("batchId") or "")) else declared
    )


def _normalize_request_media_paths(request: dict[str, Any], base: Path) -> None:
    for key in ("masterPath", "transcriptPath"):
        value = request.get("source", {}).get(key)
        if value and not Path(value).is_absolute():
            request["source"][key] = str((base / value).resolve())
    for insertion in request.get("insertions") or []:
        value = insertion.get("sourcePath")
        if value and not Path(value).is_absolute():
            insertion["sourcePath"] = str((base / value).resolve())


def _plan_paths(
    plan_path: Path,
    args: argparse.Namespace | None = None,
) -> tuple[dict[str, Any], shorts_paths.ShortsBatchPaths | None]:
    resolved_plan = plan_path.resolve()
    plan = shorts_contract.load_document(resolved_plan, "plan")
    raw_dir = getattr(args, "raw_dir", None)
    batch_dir = getattr(args, "batch_dir", None)
    if raw_dir is None and plan.get("batchRoot"):
        raw_dir = _raw_dir_from_batch_root(plan["batchRoot"])
    if raw_dir is None:
        return plan, None
    paths = shorts_paths.resolve_shorts_batch_paths(
        raw_dir,
        str(plan["batchId"]),
        batch_dir=batch_dir or plan.get("batchRoot"),
    )
    paths.validate_plan_path(resolved_plan, plan_version=str(plan["version"]))
    if plan.get("batchRoot") and Path(plan["batchRoot"]).resolve() != paths.batch_root:
        raise shorts_paths.ShortsPathError(
            f"plan batchRoot does not match resolved batch root {paths.batch_root}"
        )
    shorts_paths.register_batch(paths)
    return plan, paths


def _next_snapshot_path(
    directory: Path,
    stem: str,
    source: Path | None = None,
    *,
    payload: Mapping[str, Any] | None = None,
) -> Path:
    digest = (
        shorts_contract.content_hash(payload)
        if payload is not None
        else shorts_media.sha256_file(Path(source))
    )
    revision = 1
    while True:
        target = directory / f"{stem}-v{revision:03d}.json"
        matches = False
        if target.exists():
            if payload is not None:
                try:
                    matches = shorts_contract.content_hash(
                        _read_json_object(target)
                    ) == shorts_contract.content_hash(payload)
                except (OSError, ValueError):
                    matches = False
            else:
                matches = shorts_media.sha256_file(target) == digest
        if not target.exists() or matches:
            return target
        revision += 1


def _snapshot_request(
    source: Path,
    request: Mapping[str, Any],
    paths: shorts_paths.ShortsBatchPaths,
) -> Path:
    original = _read_json_object(source)
    if dict(request) == original:
        target = _next_snapshot_path(paths.request_root, "shorts.request", source)
        shorts_paths.snapshot_external_file(source, target)
        return target
    target = _next_snapshot_path(paths.request_root, "shorts.request", payload=request)
    if target.exists():
        existing = _read_json_object(target)
        if shorts_contract.content_hash(existing) != shorts_contract.content_hash(
            request
        ):
            raise shorts_paths.ShortsPathError(
                f"immutable request snapshot collision: {target}"
            )
    else:
        shorts_contract.atomic_write_json(target, request)
    return target


def _validate(args: argparse.Namespace) -> int:
    request, paths = _request_paths(args.request, args)
    validation_path = args.request.resolve()
    if paths is not None:
        validation_path = _snapshot_request(args.request, request, paths)
    request = shorts_plan.validate_request_file(validation_path)
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
    request, paths = _request_paths(args.request, args)
    request_path = args.request.resolve()
    if paths is not None:
        request_path = _snapshot_request(args.request, request, paths)
        output_path = args.output or paths.plans_dir / "shorts.plan-v001.json"
        output_path = paths.validate_plan_path(
            output_path, plan_version=str(request["version"])
        )
    else:
        if args.output is None:
            raise shorts_paths.ShortsPathError(
                "legacy v1.0 resolution without --raw-dir requires --output"
            )
        output_path = args.output
    output = shorts_plan.resolve_request_file(request_path, output_path)
    plan = shorts_contract.load_document(output, "plan")
    if paths is not None:
        shorts_paths.register_batch(paths, plan_hash=plan["planHash"])
    status_path = paths.status_path if paths is not None else _status_path(output)
    if not status_path.exists():
        status = _new_status(plan, output, paths=paths)
        shorts_contract.validate_document(status, "status")
        shorts_contract.atomic_write_json(status_path, status)
    print(f"resolved plan: {output}")
    return EXIT_OK


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_path(
    plan_path: Path, paths: shorts_paths.ShortsBatchPaths | None = None
) -> Path:
    return (
        paths.status_path
        if paths is not None
        else plan_path.with_name("shorts.status.json")
    )


def _new_status(
    plan: Mapping[str, Any],
    plan_path: Path,
    *,
    paths: shorts_paths.ShortsBatchPaths | None = None,
) -> dict[str, Any]:
    approval = plan.get("planApproval") or {}
    approved = approval.get("status") == "approved" and approval.get("reference")
    status = {
        "version": str(plan.get("version") or "1.0"),
        "batchId": plan["batchId"],
        "planPath": str(plan_path),
        "planHash": plan["planHash"],
        "batchState": "plan-approved" if approved else "resolved",
        "updatedAt": _now(),
        "items": [
            {
                "shortId": item["id"],
                "inputFingerprint": item["inputFingerprint"],
                "state": "pending",
                "dirty": True,
                "dirtyReasons": ["new-short"],
                "proofRevision": 0,
                "masterRevision": 0,
                "artifacts": [],
                "errors": [],
            }
            for item in plan["items"]
        ],
        "batchApprovals": (
            [
                {
                    "gate": "batch-plan",
                    "status": "approved",
                    "reference": approval["reference"],
                    "timestamp": approval.get("timestamp"),
                }
            ]
            if approved
            else []
        ),
        "blockingRisks": [],
        "batchQcSummary": None,
        "deliveryComplete": False,
    }
    if str(plan.get("version")) == "1.1":
        status.update(
            {
                "planVersion": "1.1",
                "batchRoot": str(paths.batch_root if paths else plan["batchRoot"]),
                "batchRootSource": str(
                    paths.root_source if paths else plan["batchRootSource"]
                ),
                "legacyExternalDelivery": None,
            }
        )
    return status


def _artifact(kind: str, path: Path, revision: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": str(path),
        "hash": shorts_media.sha256_file(path),
        "revision": revision,
    }


def _prepare_proof_media(
    prepare: Callable[..., Mapping[str, Any]],
    master: Path,
    work: Path,
    item: Mapping[str, Any],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    if item.get("sourceSegments"):
        return dict(
            prepare(
                master,
                work / "prepared",
                source_segments=item["sourceSegments"],
                **options,
            )
        )
    return dict(
        prepare(
            master,
            work / "prepared",
            start_sec=item["sourceRange"]["startSec"],
            end_sec=item["sourceRange"]["endSec"],
            **options,
        )
    )


def _add_prepared_insertion(
    prepared: dict[str, Any],
    request: Mapping[str, Any],
    request_path: Path,
    item: Mapping[str, Any],
    work: Path,
    fps: float,
) -> None:
    if not item.get("insertion"):
        return
    policy = next(
        row
        for row in request.get("insertions") or []
        if row["id"] == item["insertion"]["id"]
    )
    value = Path(policy["sourcePath"])
    source = (
        value.resolve()
        if value.is_absolute()
        else (request_path.parent / value).resolve()
    )
    shorts_media.validate_insertion_source(source, policy)
    assets, _source_map = shorts_media.prepare_insertion_assets(
        source,
        work / "prepared-insertion",
        approved_windows=policy["approvedWindows"],
        excluded_windows=policy.get("excludedWindows") or [],
        target_duration=item["editedDurationSec"],
        video_stream=item["insertion"]["videoStreamIndex"],
        audio_stream=item["insertion"].get("audioStreamIndex"),
        support_volume=item["insertion"]["supportVolume"],
        fps=fps,
    )
    prepared.update(assets)


def _write_prepared_lineage(
    plan: Mapping[str, Any],
    item: Mapping[str, Any],
    prepared: Mapping[str, Any],
    assets: Mapping[str, Any],
    work: Path,
) -> tuple[dict[str, str] | None, list[dict[str, Any]]]:
    windows = list(prepared.get("joinWindows") or [])
    if not item.get("sourceSegments"):
        return None, windows
    lineage = {
        "planHash": plan["planHash"],
        "shortId": str(item["id"]),
        "sourceSegments": list(item["sourceSegments"]),
        "preparedVideo": assets["baseVideo"],
        "preparedDialogue": assets["dialogueAudio"],
        "joinWindows": windows,
    }
    lineage["lineageHash"] = shorts_contract.content_hash(lineage)
    path = shorts_contract.atomic_write_json(work / "prepared-lineage.json", lineage)
    return {"path": str(path), "sha256": shorts_media.sha256_file(path)}, windows


def _prepared_artifacts(
    prepared: Mapping[str, Any],
    project: Path,
    expected: Path,
    revision: int,
    lineage: Mapping[str, str] | None,
    contact_sheet: Path | None,
) -> list[dict[str, Any]]:
    artifacts = [
        _artifact("prepared-base", prepared["baseVideo"].path, revision),
        _artifact("prepared-dialogue", prepared["dialogueAudio"].path, revision),
    ]
    if lineage:
        artifacts.append(_artifact("prepared-lineage", Path(lineage["path"]), revision))
    for key, kind in (
        ("insertionVideo", "prepared-insertion-video"),
        ("insertionAudio", "prepared-insertion-audio"),
    ):
        if key in prepared:
            artifacts.append(_artifact(kind, prepared[key].path, revision))
    artifacts.extend(
        [
            _artifact("composition", project / "composition.json", revision),
            _artifact("proof", expected, revision),
        ]
    )
    if contact_sheet and contact_sheet.is_file():
        artifacts.append(_artifact("contact-sheet", contact_sheet, revision))
    return artifacts


def _default_media_preparer(plan: Mapping[str, Any]) -> Callable[..., Any]:
    if str(plan.get("version")) == "1.1":
        return shorts_media.prepare_ordered_base_assets
    return shorts_media.prepare_base_assets


def _media_preparer(
    supplied: Callable[..., Mapping[str, Any]] | None,
    plan: Mapping[str, Any],
) -> Callable[..., Mapping[str, Any]]:
    return supplied or _default_media_preparer(plan)


def _build_one_proof(
    plan: Mapping[str, Any],
    item: Mapping[str, Any],
    plan_path: Path,
    prior: Mapping[str, Any],
    *,
    prepare: Callable[..., Mapping[str, shorts_media.PreparedAsset]],
    adapter_factory: Callable[[], HyperframesAdapter],
    preview: bool = False,
    paths: shorts_paths.ShortsBatchPaths | None = None,
) -> dict[str, Any]:
    revision = int(prior.get("proofRevision", 0)) + 1
    revision_name = f"proof-v{revision:03d}"
    work_root = (
        paths.work_dir
        if paths is not None
        else plan_path.parent / "shorts" / plan["batchId"]
    )
    work = work_root / str(item["id"]) / revision_name
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
    master = (
        master_value.resolve()
        if master_value.is_absolute()
        else (request_path.parent / master_value).resolve()
    )
    crop_mode = str(
        item["layout"].get("cropMode")
        or request["defaults"]["layout"].get("cropMode")
        or "cover"
    )
    prepare_kwargs = {
        "speed": item["speed"],
        "fps": output["fps"],
        "width": output["width"],
        "height": output["height"],
        "sample_rate": output.get("audioSampleRateHz", 48000),
        "channels": output.get("audioChannels", 2),
        "crop_mode": crop_mode,
    }
    prepared = _prepare_proof_media(prepare, master, work, item, prepare_kwargs)
    _add_prepared_insertion(
        prepared, request, request_path, item, work, plan["output"]["fps"]
    )
    assets = {
        key: value.as_contract()
        for key, value in prepared.items()
        if isinstance(value, shorts_media.PreparedAsset)
    }
    prepared_lineage_ref, required_watch_windows = _write_prepared_lineage(
        plan, item, prepared, assets, work
    )
    expected = (
        work / "renders" / f"{item['expectedOutputBasename']}-proof-v{revision:03d}.mp4"
    )
    spec = build_composition_spec(
        batch_id=plan["batchId"],
        item=item,
        output=output,
        assets=assets,
        proof_revision=revision,
        expected_output_path=expected,
        provider_tokens=plan.get("providerTokens"),
    )
    if prepared_lineage_ref is not None:
        spec.update(
            {
                "version": "1.1",
                "planVersion": str(plan.get("planVersion") or plan["version"]),
                "sourceSegments": list(item["sourceSegments"]),
                "preparedLineage": prepared_lineage_ref,
                "requiredWatchWindows": required_watch_windows,
            }
        )
        shorts_contract.validate_document(spec, "composition")
    project = compile_project(spec, work / "hyperframes")
    adapter = adapter_factory()
    checked = adapter.execute("check", project, "--snapshots", root=Path.cwd())
    if checked.exit_code:
        raise RuntimeError(
            checked.stderr or checked.stdout or "HyperFrames strict check failed"
        )
    contact_sheet = work / "qc" / "contact-sheet.jpg"
    try:
        shorts_qc.generate_contact_sheet(project, contact_sheet)
    except ValueError:
        contact_sheet = None
    rendered = adapter.execute(
        "render", project, "--output", str(expected), root=Path.cwd()
    )
    if rendered.exit_code:
        raise RuntimeError(
            rendered.stderr or rendered.stdout or "HyperFrames render failed"
        )
    if not expected.is_file():
        candidates = [
            path for path in rendered.artifact_paths if path.suffix.lower() == ".mp4"
        ]
        if candidates:
            expected = candidates[-1]
        else:
            raise RuntimeError("HyperFrames completed without an MP4 proof")
    loudness_preset = output.get("loudnessPreset")
    if loudness_preset:
        normalized = expected.with_name(f"{expected.stem}.loudnorm{expected.suffix}")
        if not _apply_loudness_preset(
            expected,
            normalized,
            preset_id=str(loudness_preset),
            preview=preview,
        ):
            raise RuntimeError("Shorts loudness normalization failed")
        normalized.replace(expected)
    artifacts = _prepared_artifacts(
        prepared,
        project,
        expected,
        revision,
        prepared_lineage_ref,
        contact_sheet,
    )
    render_profile = shorts_plan.target_render_profile(plan, preview=preview)
    return {
        **dict(prior),
        "shortId": item["id"],
        "inputFingerprint": item["inputFingerprint"],
        "state": "proof-ready",
        "dirty": False,
        "dirtyReasons": [],
        "proofRevision": revision,
        "renderProfile": render_profile,
        "artifacts": [*(prior.get("artifacts") or []), *artifacts],
        "errors": [],
        "hyperframesValidation": {"status": "passed", "strict": True},
    }


def build_proofs(
    plan_path: Path,
    *,
    short_ids: Sequence[str] | None = None,
    workers: int = 2,
    preview: bool = False,
    prepare: Callable[..., Mapping[str, Any]] | None = None,
    adapter_factory: Callable[[], HyperframesAdapter] = HyperframesAdapter,
    paths: shorts_paths.ShortsBatchPaths | None = None,
) -> tuple[Path, dict[str, Any]]:
    plan_path = plan_path.resolve()
    plan = shorts_contract.load_document(plan_path, "plan")
    prepare = _media_preparer(prepare, plan)
    shorts_contract.require_plan_approval(plan)
    status_path = _status_path(plan_path, paths)
    status = (
        shorts_contract.load_document(status_path, "status")
        if status_path.exists()
        else _new_status(plan, plan_path, paths=paths)
    )
    if status.get("planHash") != plan["planHash"]:
        status = _new_status(plan, plan_path, paths=paths)
    wanted = set(short_ids or [item["id"] for item in plan["items"]])
    unknown = wanted - {item["id"] for item in plan["items"]}
    if unknown:
        raise shorts_contract.ContractValidationError(
            f"unknown Short IDs: {', '.join(sorted(unknown))}"
        )
    dirty = shorts_plan.dirty_items(plan, status, preview=preview)
    item_status = {item["shortId"]: item for item in status["items"]}
    pending = [
        item for item in plan["items"] if item["id"] in wanted and item["id"] in dirty
    ]
    status["batchState"] = "building-proofs"
    status["updatedAt"] = _now()
    shorts_contract.atomic_write_json(status_path, status)
    futures = {}
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 4))) as pool:
        for item in pending:
            prior = item_status[item["id"]]
            prior["state"] = "preparing"
            prior["dirtyReasons"] = dirty[item["id"]]
            futures[
                pool.submit(
                    _build_one_proof,
                    plan,
                    item,
                    plan_path,
                    prior,
                    prepare=prepare,
                    adapter_factory=adapter_factory,
                    preview=preview,
                    paths=paths,
                )
            ] = item["id"]
        for future in as_completed(futures):
            short_id = futures[future]
            try:
                item_status[short_id] = future.result()
            except Exception as exc:
                prior = item_status[short_id]
                item_status[short_id] = {
                    **prior,
                    "state": "failed",
                    "dirty": True,
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
    plan, paths = _plan_paths(args.plan, args)
    try:
        shorts_contract.require_plan_approval(plan)
    except shorts_contract.ContractValidationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_APPROVAL_REQUIRED
    if args.stage == "master":
        if not args.approval_manifest:
            print(
                "--approval-manifest is required for master promotion", file=sys.stderr
            )
            return EXIT_APPROVAL_REQUIRED
        return _promote(args)
    status_path, status = build_proofs(
        args.plan,
        short_ids=args.short_ids,
        workers=args.workers,
        preview=args.preview,
        paths=paths,
    )
    failures = [
        item["shortId"] for item in status["items"] if item["state"] == "failed"
    ]
    print(f"proof status: {status_path}")
    if failures:
        print(f"proof failures: {', '.join(failures)}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_OK


def _passed_qc_state(stage: str, *, was_delivered: bool) -> str:
    if stage == "proof":
        return "proof-approved"
    return "delivered" if was_delivered else "master-qc"


def _batch_state_after_qc(
    stage: str, *, was_delivered: bool, failed: Sequence[str]
) -> str:
    if stage == "proof":
        return "proof-review"
    return "delivered" if was_delivered and not failed else "master-qc"


def _qc(args: argparse.Namespace) -> int:
    plan_path = args.plan.resolve()
    plan, paths = _plan_paths(plan_path, args)
    status_path = _status_path(plan_path, paths)
    status = shorts_contract.load_document(status_path, "status")
    was_delivered = bool(status.get("deliveryComplete")) or (
        status.get("batchState") == "delivered"
    )
    selected = set(args.short_ids or [item["id"] for item in plan["items"]])
    plan_items = {item["id"]: item for item in plan["items"]}
    failed = []
    passed = []
    for item_status in status["items"]:
        if item_status["shortId"] not in selected:
            continue
        kind = "proof" if args.stage == "proof" else "master"
        artifact = next(
            (a for a in reversed(item_status["artifacts"]) if a["kind"] == kind), None
        )
        plan_item = plan_items[item_status["shortId"]]
        output = plan["output"]
        if artifact is None:
            item_status["qc"] = {
                "status": "failed",
                "findings": [{"severity": "error", "code": f"missing-{kind}"}],
            }
        else:
            item_status["qc"] = shorts_qc.qc_proof_artifact(
                plan_item,
                artifact,
                watch_reference=item_status.get("watchReviewReference"),
                output=output,
            )
        if item_status["qc"]["status"] == "passed":
            item_status["state"] = _passed_qc_state(
                args.stage, was_delivered=was_delivered
            )
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
    status["batchState"] = _batch_state_after_qc(
        args.stage, was_delivered=was_delivered, failed=failed
    )
    status["updatedAt"] = _now()
    shorts_contract.atomic_write_json(status_path, status)
    print(json.dumps({"statusPath": str(status_path), "failed": failed}, indent=2))
    return EXIT_INVALID if failed else EXIT_OK


def _status(args: argparse.Namespace) -> int:
    _plan, paths = _plan_paths(args.plan.resolve(), args)
    path = _status_path(args.plan.resolve(), paths)
    status = shorts_contract.load_document(path, "status")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return EXIT_OK


def _promote(args: argparse.Namespace) -> int:
    plan_path = args.plan.resolve()
    plan, paths = _plan_paths(plan_path, args)
    status_path = _status_path(plan_path, paths)
    status = shorts_contract.load_document(status_path, "status")
    approval_path, approval_snapshot = _snapshot_approval(args.approval_manifest, paths)
    approvals = json.loads(approval_path.read_text(encoding="utf-8"))
    shorts_contract.validate_promotion_evidence(status, approvals)
    _apply_promotion_evidence(status, approvals)
    delivery_dir, legacy_external_delivery = _promotion_delivery_target(
        args, plan, plan_path, paths, status
    )
    result = shorts_delivery.promote_batch(
        plan,
        status,
        delivery_dir,
        batch_paths=paths,
        approval_snapshot=approval_snapshot,
        legacy_external_delivery=legacy_external_delivery,
    )
    result["status"]["updatedAt"] = _now()
    shorts_contract.validate_document(result["status"], "status")
    shorts_contract.atomic_write_json(status_path, result["status"])
    print(f"delivery manifest: {result['manifestPath']}")
    return EXIT_OK


def _snapshot_approval(
    approval_manifest: Path,
    paths: shorts_paths.ShortsBatchPaths | None,
) -> tuple[Path, Mapping[str, str] | None]:
    approval_path = approval_manifest.resolve()
    if paths is None:
        return approval_path, None
    snapshot_path = _next_snapshot_path(
        paths.approvals_dir, "approval-manifest", approval_path
    )
    snapshot = shorts_paths.snapshot_external_file(approval_path, snapshot_path)
    return snapshot_path, snapshot


def _apply_promotion_evidence(
    status: dict[str, Any], approvals: Mapping[str, Any]
) -> None:
    status["batchApprovals"] = approvals["approvals"]
    for review in approvals.get("watchReviews") or []:
        match = next(
            item for item in status["items"] if item["shortId"] == review["shortId"]
        )
        match["watchReviewReference"] = review["reference"]
        match["watchReview"] = {
            key: review[key]
            for key in (
                "reference",
                "candidateHash",
                "candidateIdentityHash",
                "dependencyLockSha256",
                "evidenceBundleSha256",
                "proofRevision",
            )
        }


def _promotion_delivery_target(
    args: argparse.Namespace,
    plan: Mapping[str, Any],
    plan_path: Path,
    paths: shorts_paths.ShortsBatchPaths | None,
    status: dict[str, Any],
) -> tuple[Path, str | None]:
    if str(plan.get("version")) == "1.1":
        if paths is None:
            raise shorts_paths.ShortsPathError(
                "v1.1 promotion requires a canonical batchRoot and --raw-dir"
            )
        delivery_dir = paths.delivery_dir
        if args.delivery_dir and args.delivery_dir.resolve() != delivery_dir:
            raise shorts_paths.ShortsPathError(
                "v1.1 rejects split --delivery-dir; use --batch-dir during "
                "resolution so plans, approvals, work, and delivery share one root"
            )
        return delivery_dir, None
    delivery_dir = (
        args.delivery_dir
        or (
            paths.delivery_dir
            if paths
            else plan_path.parent / "delivery" / plan["batchId"]
        )
    ).resolve()
    legacy = (
        str(delivery_dir)
        if paths is None or delivery_dir != paths.delivery_dir
        else None
    )
    status["legacyExternalDelivery"] = legacy
    if args.delivery_dir:
        print(
            "warning: --delivery-dir is supported only for v1.0 during the "
            "compatibility window; resolve with --raw-dir/--batch-dir to migrate",
            file=sys.stderr,
        )
    return delivery_dir, legacy


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
    except (
        shorts_contract.ContractValidationError,
        shorts_delivery.DeliveryError,
        OSError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID
    return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
