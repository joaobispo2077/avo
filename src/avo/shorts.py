"""Executable batch workflow for parameter-driven YouTube Shorts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from avo import (
    shorts_contract,
    shorts_delivery,
    shorts_media,
    shorts_motion,
    shorts_paths,
    shorts_plan,
    shorts_qc,
    shorts_review,
)
from avo.adapters.motion import hyperframes as hyperframes_motion
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
    from dataclasses import replace

    from avo import loudness_profiles, render

    profile = loudness_profiles.resolve_loudness_profile(preset_override=preset_id)
    if preview:
        profile = replace(profile, true_peak_dbtp=min(profile.true_peak_dbtp, -2.0))
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
        help="render proofs at output.previewLongSide (default 640), preserving aspect ratio",
    )
    build.add_argument("--approval-manifest", type=Path)
    build.add_argument("--delivery-dir", type=Path)
    _add_batch_root_arguments(build)
    qc = subparsers.add_parser("qc", help="evaluate proof or master artifacts")
    qc.add_argument("plan", type=Path)
    qc.add_argument("--stage", choices=("proof", "master"), required=True)
    qc.add_argument("--short", action="append", dest="short_ids")
    _add_batch_root_arguments(qc)
    review = subparsers.add_parser(
        "review", help="run serial exact-proof ASR, vision and QC"
    )
    review.add_argument("plan", type=Path)
    review.add_argument("--short", action="append", dest="short_ids")
    review.add_argument("--device", choices=("cpu",), default="cpu")
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
    *,
    pin_motion: bool = False,
) -> tuple[dict[str, Any], shorts_paths.ShortsBatchPaths | None]:
    request = _read_json_object(request_path)
    version = str(request.get("version") or "1.0")
    raw_dir = _request_raw_dir(request, args)
    if raw_dir is None and shorts_contract.uses_canonical_root(version):
        raise shorts_paths.ShortsPathError(
            "canonical Shorts requests require --raw-dir (and optional --batch-dir) "
            "so the canonical batch root can be resolved before work"
        )
    if raw_dir is None:
        if pin_motion:
            _pin_validated_request_motion(request, None)
        return request, None
    raw_dir = Path(raw_dir).expanduser().resolve()
    batch_dir = _request_batch_dir(request, args, raw_dir)
    paths = shorts_paths.resolve_shorts_batch_paths(
        raw_dir,
        str(request.get("batchId") or ""),
        batch_dir=batch_dir,
    )
    _normalize_request_media_paths(request, request_path.parent)
    if shorts_contract.uses_canonical_root(version):
        request["batchRoot"] = str(paths.batch_root)
        request["batchRootSource"] = paths.root_source
    if pin_motion:
        _pin_validated_request_motion(request, paths)
    else:
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


def _pin_request_motion(
    request: dict, paths: shorts_paths.ShortsBatchPaths | None
) -> None:
    from avo.motion import inspect_motion
    from avo.video_context import resolve_context, resolve_context_motion_selection

    selected = request["defaults"].get("motionEngine")
    invocation = {"engine": selected} if selected is not None else None
    if paths is not None and (paths.raw_dir / "avo.project.json").is_file():
        context = resolve_context(raw_dir=paths.raw_dir)
        selection = resolve_context_motion_selection(context, invocation=invocation)
    else:
        selection = inspect_motion(invocation=invocation)["selection"]
    request["defaults"]["motionEngine"] = selection["engine"]


def _pin_validated_request_motion(request, paths):
    shorts_contract.validate_document(request, "request")
    _pin_request_motion(request, paths)
    shorts_contract.validate_document(request, "request")


def _resolve(args: argparse.Namespace) -> int:
    request, paths = _request_paths(args.request, args, pin_motion=True)
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
    output = shorts_plan.resolve_request_file(
        request_path, output_path, motion_engine=request["defaults"]["motionEngine"]
    )
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
    return datetime.now(UTC).isoformat()


def _status_path(
    plan_path: Path, paths: shorts_paths.ShortsBatchPaths | None = None
) -> Path:
    return (
        paths.status_path
        if paths is not None
        else plan_path.with_name("shorts.status.json")
    )


_REVISION_KEYS = ("proofRevision", "proofArtifactRevision", "masterRevision")


def _canonical_status_fields(
    plan: Mapping[str, Any], paths: shorts_paths.ShortsBatchPaths | None
) -> dict[str, Any]:
    return {
        "planVersion": str(plan.get("planVersion") or plan["version"]),
        "batchRoot": str(paths.batch_root if paths else plan["batchRoot"]),
        "batchRootSource": str(paths.root_source if paths else plan["batchRootSource"]),
        "legacyExternalDelivery": None,
    }


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
                **shorts_motion.pinned_fields(item),
                "inputFingerprint": item["inputFingerprint"],
                "state": "pending",
                "dirty": True,
                "dirtyReasons": ["new-short"],
                "proofRevision": 0,
                "proofArtifactRevision": 0,
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
    if shorts_contract.uses_canonical_root(plan.get("version")):
        status.update(_canonical_status_fields(plan, paths))
    return status


def _carry_revision_watermarks(
    old_status: Mapping[str, Any], new_status: dict[str, Any]
) -> None:
    """Keep proof/master watermarks so a new plan cannot overwrite old renders."""
    previous = {str(row["shortId"]): row for row in (old_status.get("items") or [])}
    for row in new_status["items"]:
        prior = previous.get(str(row["shortId"]))
        if not prior:
            continue
        for key in _REVISION_KEYS:
            row[key] = max(int(row.get(key) or 0), int(prior.get(key) or 0))


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
    dialogue = prepared.get("dialogueAudio")
    insertion_audio = prepared.get("insertionAudio")
    if isinstance(dialogue, shorts_media.PreparedAsset) and isinstance(
        insertion_audio, shorts_media.PreparedAsset
    ):
        mixed = work / "prepared" / "dialogue-mixed.m4a"
        prepared["dialogueAudio"] = shorts_media.mix_ducked_bed_into_dialogue(
            dialogue.path,
            insertion_audio.path,
            mixed,
            duration_sec=dialogue.duration_sec,
        )


def _add_prepared_sfx(
    prepared: dict[str, Any],
    request: Mapping[str, Any],
    request_path: Path,
    item: Mapping[str, Any],
    work: Path,
) -> None:
    hits = list(item.get("sfxHits") or [])
    if not hits:
        return
    library = ((request.get("defaults") or {}).get("sfx") or {}).get("library") or {}
    prepared.update(
        shorts_media.prepare_sfx_assets(
            hits,
            library,
            work / "prepared-sfx",
            request_path=request_path,
        )
    )


def _add_prepared_audio_bed(
    prepared: dict[str, Any],
    request_path: Path,
    item: Mapping[str, Any],
    work: Path,
    *,
    channels: int,
) -> None:
    policy = item.get("audioBed")
    if not policy:
        return
    value = Path(str(policy["path"]))
    source = (
        value.resolve()
        if value.is_absolute()
        else (request_path.parent / value).resolve()
    )
    if not source.is_file():
        raise RuntimeError(f"audio bed source does not exist: {source}")
    actual = shorts_media.sha256_file(source)
    if actual != policy["fingerprint"]:
        raise RuntimeError(f"audio bed fingerprint mismatch: {policy['id']}")
    dialogue = prepared["dialogueAudio"]
    prepared["audioBedSource"] = shorts_media.PreparedAsset(
        source,
        actual,
        shorts_media.probe_duration_sec(shorts_media.probe_media(source)),
        False,
    )
    prepared["dialogueAudio"] = shorts_media.mix_timed_audio_bed(
        dialogue,
        source,
        work / "prepared" / "dialogue-with-audio-bed.m4a",
        policy=policy,
        channels=channels,
    )


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
        "audioTreatment": item.get("audioTreatment"),
        "visualInserts": list(item.get("visualInserts") or []),
        "audioBed": item.get("audioBed"),
        "audioBedSource": (
            prepared["audioBedSource"].as_contract()
            if isinstance(prepared.get("audioBedSource"), shorts_media.PreparedAsset)
            else None
        ),
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
    artifacts.extend(_prepared_audio_review_artifacts(prepared, revision))
    if lineage:
        artifacts.append(_artifact("prepared-lineage", Path(lineage["path"]), revision))
    for key, kind in (
        ("insertionVideo", "prepared-insertion-video"),
        ("insertionAudio", "prepared-insertion-audio"),
    ):
        if key in prepared:
            artifacts.append(_artifact(kind, prepared[key].path, revision))
    for key, value in prepared.items():
        if key.startswith("sfx") and isinstance(value, shorts_media.PreparedAsset):
            artifacts.append(_artifact("prepared-sfx", value.path, revision))
    artifacts.extend(
        [
            _artifact("composition", project / "composition.json", revision),
            _artifact("proof", expected, revision),
        ]
    )
    if contact_sheet and contact_sheet.is_file():
        artifacts.append(_artifact("contact-sheet", contact_sheet, revision))
    return artifacts


def _prepared_audio_review_artifacts(prepared, revision):
    artifacts = []
    for key, kind in (
        ("dialogueUntreated", "prepared-dialogue-untreated"),
        ("dialogueRemovedSignal", "prepared-dialogue-removed-signal"),
        ("audioBedSource", "prepared-audio-bed"),
    ):
        value = prepared.get(key)
        if isinstance(value, shorts_media.PreparedAsset):
            artifacts.append(_artifact(kind, value.path, revision))
    return artifacts


def _default_media_preparer(plan: Mapping[str, Any]) -> Callable[..., Any]:
    if shorts_contract.uses_canonical_root(plan.get("version")):
        return shorts_media.prepare_ordered_base_assets
    return shorts_media.prepare_base_assets


def _media_preparer(
    supplied: Callable[..., Mapping[str, Any]] | None,
    plan: Mapping[str, Any],
) -> Callable[..., Mapping[str, Any]]:
    return supplied or _default_media_preparer(plan)


def _hyperframes_command_error(result: Any, action: str) -> str:
    """Prefer stdout — HyperFrames writes layout findings there, GPU probe on stderr."""
    chunks = [
        part.strip()
        for part in (result.stdout, result.stderr)
        if part and str(part).strip()
    ]
    return "\n".join(chunks) or f"HyperFrames {action} failed"


def _only_slow_media_warning(result: Any) -> bool:
    issue_lines = [
        line.strip()
        for line in str(result.stdout or "").splitlines()
        if line.strip().startswith(("⚠", "✗"))
    ]
    return bool(issue_lines) and all("clip_media_fit" in line for line in issue_lines)


def _fidelity_segments(item):
    if item.get("insertion"):
        raise RuntimeError(
            "10-bit Shorts require timed visualInserts, not legacy split media"
        )
    if item["layout"]["mode"] == "split" and not item.get("visualInserts"):
        raise RuntimeError("10-bit split Shorts require timed visualInserts")
    if not item.get("sourceSegments"):
        raise RuntimeError("10-bit Shorts require locked original sourceSegments")
    return item["sourceSegments"]


def _fidelity_lock(plan, item, spec, overlay, mixed, receipt=None):
    lock = {
        "plan": str(plan["planHash"]),
        "item": str(item["inputFingerprint"]),
        "composition": shorts_contract.content_hash(spec),
        "source": str(item["sourceSegments"][0]["sourceFingerprint"]),
        "graphics-alpha": shorts_media.sha256_file(overlay),
        "mixed-audio": mixed["sha256"],
        **{
            f"visual:{row['id']}": str(row["sha256"])
            for row in item.get("visualInserts", [])
        },
        **{
            f"asset:{key}": asset["hash"]
            for key, asset in spec["assets"].items()
            if isinstance(asset, Mapping)
        },
    }
    if receipt is None:
        lock.update(_fidelity_implementation_hashes())
    else:
        lock.update(_fidelity_implementation_hashes("code-drawn"))
        lock.update(shorts_motion.receipt_lock(receipt))
    return lock


def _fidelity_implementation_hashes(engine="hyperframes"):
    from avo import shorts_fidelity, shorts_fidelity_audio

    template_root = (
        Path(hyperframes_motion.__file__).parents[2]
        / "templates"
        / "shorts_hyperframes"
    )
    common = (
        Path(__file__),
        Path(shorts_fidelity.__file__),
        Path(shorts_fidelity_audio.__file__),
    )
    paths = (
        (*common, Path(shorts_motion.__file__))
        if engine == "code-drawn"
        else (
            *common,
            Path(hyperframes_motion.__file__),
            template_root / "index.html",
            template_root / "runtime.js",
            template_root / "styles.css",
            template_root / "hyperframes.json",
        )
    )
    hashes = {
        f"implementation:{path.name}": shorts_media.sha256_file(path) for path in paths
    }
    if engine == "code-drawn":
        from avo.motion import _drawing_generator_identity

        generator = _drawing_generator_identity()
        hashes.update(
            {
                "generator:code-drawn-executable": generator["executableSha256"],
                "generator:code-drawn-source": generator["sourceSha256"],
            }
        )
    return hashes


def _render_graphics_alpha(spec, work, overlay, fps, adapter):
    if shorts_motion.engine(spec) != "hyperframes":
        raise RuntimeError(
            "code-drawn graphics require an admitted canonical alpha; HyperFrames styles are unsupported"
        )
    overlay_spec = {
        **spec,
        "renderLayers": "graphics-only",
        "expectedOutputPath": str(overlay),
    }
    graphics = compile_project(overlay_spec, work / "hyperframes-alpha")
    rendered = adapter.execute(
        "render",
        graphics,
        "--format",
        "webm",
        "--fps",
        fps,
        "--quality",
        "high",
        "--workers",
        "2",
        "--output",
        str(overlay),
        root=Path.cwd(),
    )
    if rendered.exit_code or not overlay.is_file():
        raise RuntimeError(
            _hyperframes_command_error(rendered, "graphics-alpha render")
        )


def _render_source_fidelity(
    plan: Mapping[str, Any],
    item: Mapping[str, Any],
    source: Path,
    output: Mapping[str, Any],
    spec: Mapping[str, Any],
    work: Path,
    expected: Path,
    adapter: HyperframesAdapter | None,
    *,
    workspace=None,
) -> dict[str, Any] | None:
    """Composite selected graphics alpha over original picture and independent audio."""
    from fractions import Fraction

    from avo import shorts_fidelity, shorts_fidelity_audio

    segments = _fidelity_segments(item)
    fps = str(
        output.get("frameRateRational")
        or Fraction(str(output["fps"])).limit_denominator(100000)
    )
    overlay = work / "renders" / "graphics-alpha.webm"
    receipt = None
    if shorts_motion.engine(spec) == "code-drawn":
        overlay, receipt = shorts_motion.admitted_alpha(spec, workspace, item, output)
    mixed = shorts_fidelity_audio.mix_short_audio(
        spec["assets"],
        item,
        work / "prepared" / "mixed-audio.wav",
        channels=int(output.get("audioChannels", 2)),
        true_peak=-1.5,
    )
    source_hash = str(segments[0]["sourceFingerprint"])
    microproof_gate = shorts_fidelity.build_microproofs(
        source,
        work / "microproofs",
        plan_hash=str(plan["planHash"]),
        item=item,
        source_sha256=source_hash,
        width=int(output["width"]),
        height=int(output["height"]),
        fps=fps,
        mixed_audio_path=Path(mixed["path"]),
        mixed_audio_sha256=mixed["sha256"],
        **(
            {
                "graphics_review": "admitted code-drawn alpha; separate human visual and caption review pending"
            }
            if receipt is not None
            else {}
        ),
    )
    if receipt is None:
        _render_graphics_alpha(spec, work, overlay, fps, adapter)
    lock = _fidelity_lock(plan, item, spec, overlay, mixed, receipt)
    lock["microproof-gate"] = microproof_gate["sha256"]
    implementation = shorts_fidelity.registered_implementation()
    lock["implementation:registered-source-fidelity"] = implementation["sha256"]
    result = shorts_fidelity.render_fidelity(
        source,
        expected,
        source_segments=segments,
        source_sha256=source_hash,
        canonical_lock=lock,
        width=int(output["width"]),
        height=int(output["height"]),
        fps=fps,
        speed=float(item["speed"]),
        visual_inserts=item.get("visualInserts", []),
        punch_ins=item.get("punchIns", []),
        overlay_path=overlay,
        overlay_sha256=lock["graphics-alpha"],
        mixed_audio_path=Path(mixed["path"]),
        mixed_audio_sha256=mixed["sha256"],
        preset="fast" if output.get("preview") else "slow",
    )
    if receipt is not None:
        shorts_motion.revalidate_alpha(spec, workspace, item, output, receipt)
    result["audioMix"] = mixed
    result["implementationRef"] = implementation
    result["microproofGate"] = microproof_gate
    shorts_contract.atomic_write_json(work / "source-fidelity.json", result)
    return receipt


def _render_hyperframes_picture(adapter, project, expected, fps):
    rendered = adapter.execute(
        "render",
        project,
        "--fps",
        fps,
        "--output",
        str(expected),
        root=Path.cwd(),
    )
    if rendered.exit_code:
        raise RuntimeError(_hyperframes_command_error(rendered, "render"))
    if expected.is_file():
        return expected
    candidates = [
        path for path in rendered.artifact_paths if path.suffix.lower() == ".mp4"
    ]
    if not candidates:
        raise RuntimeError("HyperFrames completed without an MP4 proof")
    return candidates[-1]


def _check_hyperframes_project(adapter, project, fidelity):
    checked = adapter.execute(
        "check", project, "--snapshots", "--timeout", "120000", root=Path.cwd()
    )
    if checked.exit_code and fidelity and _only_slow_media_warning(checked):
        checked = adapter.execute(
            "check",
            project,
            "--snapshots",
            "--timeout",
            "120000",
            "--allow-warnings",
            root=Path.cwd(),
        )
    if checked.exit_code:
        raise RuntimeError(_hyperframes_command_error(checked, "strict check"))


def _render_selected_proof(
    plan, item, master, output, spec, work, expected, adapter_factory, workspace
):
    fidelity = output.get("pixelFormat") == "yuv420p10le"
    if shorts_motion.engine(spec) == "code-drawn":
        project = work / "composition"
        shorts_contract.atomic_write_json(project / "composition.json", spec)
        receipt = _render_source_fidelity(
            plan, item, master, output, spec, work, expected, None, workspace=workspace
        )
        extension = receipt["parameters"]["codeDrawn"]
        validation = {
            "codeDrawnValidation": {
                "status": "passed",
                "receiptRecordHash": receipt["recordHash"],
                "inputLockSha256": extension["inputLockRef"]["sha256"],
            }
        }
        return project, None, expected, validation
    project = compile_project(spec, work / "hyperframes")
    adapter = adapter_factory()
    _check_hyperframes_project(adapter, project, fidelity)
    contact_sheet = work / "qc" / "contact-sheet.jpg"
    try:
        shorts_qc.generate_contact_sheet(project, contact_sheet)
    except ValueError:
        contact_sheet = None
    if fidelity:
        _render_source_fidelity(
            plan, item, master, output, spec, work, expected, adapter
        )
    else:
        fps = str(
            output.get("frameRateRational")
            or Fraction(str(output["fps"])).limit_denominator(100000)
        )
        expected = _render_hyperframes_picture(adapter, project, expected, fps)
    return (
        project,
        contact_sheet,
        expected,
        {"hyperframesValidation": {"status": "passed", "strict": True}},
    )


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
        preview_profile = shorts_plan.target_render_profile(plan, preview=True)
        output = {
            **output,
            "width": preview_profile["width"],
            "height": preview_profile["height"],
            "preview": True,
        }
    workspace = shorts_motion.require_proof(item, output, paths)
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
        "audio_treatment": item.get("audioTreatment"),
    }
    prepared = _prepare_proof_media(prepare, master, work, item, prepare_kwargs)
    tp_ceiling = (
        shorts_media.SFX_DIALOGUE_TP_CEILING_DBTP
        if item.get("sfxHits")
        else shorts_media.VOICE_TP_CEILING_DBTP
    )
    prepared["dialogueAudio"] = shorts_media.apply_dialogue_gain_if_needed(
        prepared["dialogueAudio"],
        work
        / "prepared"
        / (
            "dialogue-gained.wav"
            if item.get("audioTreatment")
            else "dialogue-gained.m4a"
        ),
        tp_ceiling=tp_ceiling,
        channels=int(output.get("audioChannels", 2)),
    )
    _add_prepared_audio_bed(
        prepared,
        request_path,
        item,
        work,
        channels=int(output.get("audioChannels", 2)),
    )
    _add_prepared_insertion(
        prepared, request, request_path, item, work, plan["output"]["fps"]
    )
    _add_prepared_sfx(prepared, request, request_path, item, work)
    assets = shorts_media.composition_assets(prepared)
    prepared_lineage_ref, required_watch_windows = _write_prepared_lineage(
        plan, item, prepared, assets, work
    )
    expected = (
        work / "renders" / f"{item['expectedOutputBasename']}-proof-v{revision:03d}.mp4"
    )
    composition_builder = (
        shorts_motion.composition_spec
        if workspace is not None
        else build_composition_spec
    )
    spec = composition_builder(
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
                "version": str(plan.get("version") or spec.get("version") or "1.1"),
                "planVersion": str(plan.get("planVersion") or plan["version"]),
                "sourceSegments": list(item["sourceSegments"]),
                "preparedLineage": prepared_lineage_ref,
                "requiredWatchWindows": required_watch_windows,
            }
        )
        shorts_contract.validate_document(spec, "composition")
    project, contact_sheet, expected, validation = _render_selected_proof(
        plan, item, master, output, spec, work, expected, adapter_factory, workspace
    )
    fidelity = output.get("pixelFormat") == "yuv420p10le"
    shorts_media.ensure_audio_channels(
        expected,
        channels=int(output.get("audioChannels", 2)),
        sample_rate=int(output.get("audioSampleRateHz", 48000)),
    )
    loudness_preset = output.get("loudnessPreset")
    if loudness_preset and not fidelity:
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
    if fidelity:
        artifacts.append(
            _artifact("source-fidelity", work / "source-fidelity.json", revision)
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
        "proofArtifactRevision": revision,
        "renderProfile": render_profile,
        "artifacts": [*(prior.get("artifacts") or []), *artifacts],
        "errors": [],
        **shorts_motion.pinned_fields(item),
        **validation,
    }


def _load_or_reset_status(
    plan: Mapping[str, Any],
    plan_path: Path,
    status_path: Path,
    *,
    paths: shorts_paths.ShortsBatchPaths | None,
) -> dict[str, Any]:
    status = (
        shorts_contract.load_document(status_path, "status")
        if status_path.exists()
        else _new_status(plan, plan_path, paths=paths)
    )
    if status.get("planHash") != plan["planHash"]:
        previous = status
        status = _new_status(plan, plan_path, paths=paths)
        _carry_revision_watermarks(previous, status)
        try:
            previous_plan = shorts_contract.load_document(previous["planPath"], "plan")
        except (OSError, KeyError, shorts_contract.ContractValidationError):
            previous_plan = {}
        shared_inputs = (
            "batchId",
            "sourceFingerprint",
            "source",
            "providerTokensFingerprint",
            "output",
            "batchRoot",
        )
        if previous_plan.get("planHash") == previous.get("planHash") and all(
            previous_plan.get(key) == plan.get(key) for key in shared_inputs
        ):
            prior_rows = {row["shortId"]: row for row in previous["items"]}
            # Item approvals remain bound to their original exact candidates.
            status["items"] = [
                dict(prior_rows[row["shortId"]])
                if prior_rows.get(row["shortId"], {}).get("inputFingerprint")
                == row["inputFingerprint"]
                else row
                for row in status["items"]
            ]
    return status


def _fidelity_report_current(row, implementations):
    revision = int(row.get("proofArtifactRevision") or row.get("proofRevision") or 0)
    artifacts = {
        artifact["kind"]: artifact
        for artifact in row.get("artifacts", [])
        if int(artifact.get("revision", 0)) == revision
    }
    try:
        report_artifact, proof = artifacts["source-fidelity"], artifacts["proof"]
        report_path = Path(report_artifact["path"])
        if shorts_media.sha256_file(report_path) != report_artifact["hash"]:
            return False
        report = _read_json_object(report_path)
        return _fidelity_report_matches(report, proof, implementations)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _fidelity_report_matches(report, proof, implementations):
    lock = report["canonicalInputLock"]
    if not isinstance(lock, Mapping):
        return False
    if any(lock.get(key) != value for key, value in implementations.items()):
        return False
    if (
        report["implementationRef"]["sha256"]
        != implementations["implementation:registered-source-fidelity"]
    ):
        return False
    return (
        Path(report["path"]).resolve() == Path(proof["path"]).resolve()
        and report["sha256"] == proof["hash"]
        and shorts_media.sha256_file(Path(proof["path"])) == proof["hash"]
    )


def _current_fidelity_implementations(plan, item, paths):
    from avo import shorts_fidelity

    if shorts_motion.engine(item) == "code-drawn":
        implementations = _fidelity_implementation_hashes("code-drawn")
        workspace = shorts_motion.workspace_from_paths(paths)
        _, receipt = shorts_motion.admitted_alpha(item, workspace, item, plan["output"])
        implementations.update(shorts_motion.receipt_lock(receipt))
    else:
        implementations = _fidelity_implementation_hashes()
    implementations["implementation:registered-source-fidelity"] = (
        shorts_fidelity.registered_implementation()["sha256"]
    )
    return implementations


def _current_fidelity_report(plan, row, item, paths):
    try:
        implementations = _current_fidelity_implementations(plan, item, paths)
        return _fidelity_report_current(row, implementations)
    except (OSError, ValueError, KeyError, RuntimeError, TypeError):
        return False


def _mark_stale_fidelity_proofs(plan, status, *, paths=None):
    if plan.get("output", {}).get("pixelFormat") != "yuv420p10le":
        return
    items = {item["id"]: item for item in plan.get("items", [])}
    for row in status["items"]:
        if not (row.get("proofArtifactRevision") or row.get("proofRevision")):
            continue
        item = items.get(row.get("shortId"), row)
        if not _current_fidelity_report(plan, row, item, paths):
            row["dirty"] = True
            reasons = row.setdefault("dirtyReasons", [])
            if "render-implementation-changed" not in reasons:
                reasons.append("render-implementation-changed")


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
    status = _load_or_reset_status(plan, plan_path, status_path, paths=paths)
    wanted = set(short_ids or [item["id"] for item in plan["items"]])
    unknown = wanted - {item["id"] for item in plan["items"]}
    if unknown:
        raise shorts_contract.ContractValidationError(
            f"unknown Short IDs: {', '.join(sorted(unknown))}"
        )
    _mark_stale_fidelity_proofs(plan, status, paths=paths)
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
                    "proofRevision": int(prior.get("proofRevision") or 0) + 1,
                    "proofArtifactRevision": int(
                        prior.get("proofArtifactRevision") or 0
                    ),
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


def _qc_output_profile(
    plan: Mapping[str, Any], item_status: Mapping[str, Any], stage: str
) -> Mapping[str, Any]:
    render_profile = item_status.get("renderProfile") or {}
    if stage != "proof" or not render_profile.get("preview"):
        return plan["output"]
    return {
        **plan["output"],
        "width": int(render_profile["width"]),
        "height": int(render_profile["height"]),
    }


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
        output = _qc_output_profile(plan, item_status, args.stage)
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


def _review(args: argparse.Namespace) -> int:
    result = shorts_review.review_batch(
        args.plan.resolve(), short_ids=args.short_ids, device=args.device
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_INVALID if result["failed"] else EXIT_OK


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
    if shorts_contract.uses_canonical_root(plan.get("version")):
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
        if args.action == "review":
            return _review(args)
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
