"""AVO core command-line entry points backed by timeline application services."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from avo.timeline.lifecycle import (
    LifecycleError,
    PipelineRunStore,
    PipelineState,
    TransitionFacts,
)
from avo.timeline.store import StoreError
from avo.timeline.workspace import TimelineWorkspace, WorkspaceError


def _project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--video-id", default="")
    parser.add_argument("--json", action="store_true", dest="as_json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avo")
    sub = parser.add_subparsers(dest="command", required=True)

    pipeline = sub.add_parser("pipeline")
    pipeline_sub = pipeline.add_subparsers(dest="pipeline_command", required=True)
    for name in ("run", "status", "verify-commands"):
        item = pipeline_sub.add_parser(name)
        _project_arg(item)
    pipeline_resume = pipeline_sub.add_parser("resume")
    _project_arg(pipeline_resume)
    pipeline_resume.add_argument("--actor", required=True)
    pipeline_resume.add_argument("--reason", required=True)
    pipeline_resume.add_argument("--recovery-event", required=True)
    pipeline_stage = pipeline_sub.add_parser("stage")
    _project_arg(pipeline_stage)
    pipeline_stage.add_argument("--stage", required=True)
    pipeline_stage.add_argument("--payload", type=Path)
    pipeline_stage.add_argument("--actor", default="avo.pipeline")
    pipeline_stage.add_argument("--reason", default="")

    timeline = sub.add_parser("timeline")
    timeline_sub = timeline.add_subparsers(dest="timeline_command", required=True)
    for name in ("init", "status", "validate"):
        item = timeline_sub.add_parser(name)
        _project_arg(item)
    resume = timeline_sub.add_parser("resume")
    _project_arg(resume)
    resume.add_argument("--actor", required=True)
    resume.add_argument("--reason", required=True)
    resume.add_argument("--recovery-event", required=True)

    sync = sub.add_parser("sync")
    sync_sub = sync.add_subparsers(dest="sync_command", required=True)
    inventory = sync_sub.add_parser("inventory")
    _project_arg(inventory)
    inventory.add_argument("--source", type=Path, action="append", required=True)
    calibrate = sync_sub.add_parser("calibrate")
    _project_arg(calibrate)
    calibrate.add_argument(
        "--kind",
        choices=("constant-offset", "linear-drift", "piecewise", "not-applicable"),
        required=True,
    )
    calibrate.add_argument("--picture", type=Path)
    calibrate.add_argument("--audio", type=Path)
    calibrate.add_argument("--picture-stream", default="v:0")
    calibrate.add_argument("--audio-stream", default="a:0")
    calibrate.add_argument("--channel", type=int, action="append", default=[0])
    calibrate.add_argument("--offset-ms", type=int, default=0)
    calibrate.add_argument("--tolerance-ms", type=int, default=20)
    calibrate.add_argument("--sample", action="append", default=[])
    calibrate.add_argument("--control-point", action="append", default=[])
    calibrate.add_argument("--rate-num", type=int, default=1)
    calibrate.add_argument("--rate-den", type=int, default=1)
    calibrate.add_argument("--source", type=Path, action="append", default=[])
    calibrate.add_argument("--actor", required=True)
    calibrate.add_argument("--reason", required=True)
    validate_sync = sync_sub.add_parser("validate")
    _project_arg(validate_sync)
    decide_sync = sync_sub.add_parser("decide")
    _project_arg(decide_sync)
    decide_sync.add_argument(
        "--decision",
        choices=("approved", "rejected", "changes-requested"),
        required=True,
    )
    decide_sync.add_argument("--candidate-sha256", required=True)
    decide_sync.add_argument("--evidence-sha256", required=True)
    decide_sync.add_argument("--actor", required=True)
    decide_sync.add_argument("--reason", required=True)

    animation = sub.add_parser("animation")
    animation_sub = animation.add_subparsers(dest="animation_command", required=True)
    author_animation = animation_sub.add_parser("author")
    _project_arg(author_animation)
    author_animation.add_argument("--strategy", type=Path, required=True)
    author_animation.add_argument("--actor", required=True)
    author_animation.add_argument("--reason", required=True)
    propose_animation = animation_sub.add_parser("propose")
    propose_animation.add_argument("--catalog", type=Path, required=True)
    propose_animation.add_argument("--provider", required=True)
    propose_animation.add_argument("--pattern", type=Path, required=True)
    propose_animation.add_argument("--actor", required=True)
    propose_animation.add_argument("--intent-reference", required=True)
    decide_animation = animation_sub.add_parser("decide")
    decide_animation.add_argument("--catalog", type=Path, required=True)
    decide_animation.add_argument("--provider", required=True)
    decide_animation.add_argument("--proposal", type=Path, required=True)
    decide_animation.add_argument(
        "--decision", choices=("approved", "rejected"), required=True
    )
    decide_animation.add_argument("--actor", required=True)
    decide_animation.add_argument("--reason", required=True)
    recommend_animation = animation_sub.add_parser("recommend")
    recommend_animation.add_argument("--catalog", type=Path, required=True)
    recommend_animation.add_argument("--provider", required=True)
    recommend_animation.add_argument("--diagnosis", type=Path, required=True)
    recommend_animation.add_argument("--evidence-sha256", required=True)
    reject_animation = animation_sub.add_parser("reject-recommendation")
    reject_animation.add_argument("--catalog", type=Path, required=True)
    reject_animation.add_argument("--provider", required=True)
    reject_animation.add_argument("--pattern-id", required=True)
    reject_animation.add_argument("--evidence-sha256", required=True)
    reject_animation.add_argument("--actor", required=True)
    reject_animation.add_argument("--reason", required=True)

    tracks = sub.add_parser("tracks")
    tracks_sub = tracks.add_subparsers(dest="tracks_command", required=True)
    resolve_tracks = tracks_sub.add_parser("resolve")
    _project_arg(resolve_tracks)
    resolve_tracks.add_argument("--snapshot", type=Path, required=True)
    resolve_tracks.add_argument("--actor", required=True)
    resolve_tracks.add_argument("--reason", required=True)
    inspect_tracks = tracks_sub.add_parser("inspect")
    _project_arg(inspect_tracks)
    render_tracks = tracks_sub.add_parser("render")
    _project_arg(render_tracks)
    render_tracks.add_argument("--output", type=Path, required=True)
    render_tracks.add_argument("--profile", default="preview")

    bmap = sub.add_parser("bmap")
    bmap_sub = bmap.add_subparsers(dest="bmap_command", required=True)
    for operation in ("create", "revise"):
        item = bmap_sub.add_parser(operation)
        _project_arg(item)
        item.add_argument("--snapshot", type=Path, required=True)
        item.add_argument("--actor", required=True)
        item.add_argument("--reason", required=True)
    bmap_status = bmap_sub.add_parser("status")
    _project_arg(bmap_status)
    bmap_rebase = bmap_sub.add_parser("rebase")
    _project_arg(bmap_rebase)
    bmap_rebase.add_argument("--mapped-ranges", type=Path, required=True)
    bmap_rebase.add_argument("--actor", required=True)
    bmap_rebase.add_argument("--reason", required=True)

    cmap = sub.add_parser("cmap")
    cmap_sub = cmap.add_subparsers(dest="cmap_command", required=True)
    create_cmap = cmap_sub.add_parser("create")
    _project_arg(create_cmap)
    create_cmap.add_argument("--snapshot", type=Path, required=True)
    create_cmap.add_argument("--actor", required=True)
    create_cmap.add_argument("--reason", required=True)
    project_cmap = cmap_sub.add_parser("project")
    _project_arg(project_cmap)
    project_cmap.add_argument("--revision-id", required=True)
    render_cmap = cmap_sub.add_parser("render")
    _project_arg(render_cmap)
    render_cmap.add_argument("--revision-id", required=True)
    render_cmap.add_argument("--output", type=Path, required=True)
    render_cmap.add_argument("--profile", default="draft")

    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    run_review = review_sub.add_parser("run")
    _project_arg(run_review)
    run_review.add_argument(
        "--checkpoint",
        default="cut-proof",
        choices=("cut-proof", "motion-proof", "pre-master", "deliver"),
    )
    run_review.add_argument("--candidate", type=Path)
    run_review.add_argument("--materialization", type=Path)
    run_review.add_argument("--dependency", action="append", default=[])
    run_review.add_argument("--window", action="append", default=[])
    run_review.add_argument("--term", action="append", default=[])
    run_review.add_argument("--name", action="append", default=[])
    run_review.add_argument("--profile", default="draft")
    decide_review = review_sub.add_parser("decide")
    _project_arg(decide_review)
    decide_review.add_argument(
        "--decision",
        choices=("approved", "rejected", "changes-requested"),
        required=True,
    )
    decide_review.add_argument("--revision-id", required=True)
    decide_review.add_argument("--review", type=Path, required=True)
    decide_review.add_argument("--materialization", type=Path, required=True)
    decide_review.add_argument("--actor", required=True)
    decide_review.add_argument("--reason", required=True)

    deliver = sub.add_parser("deliver")
    deliver_sub = deliver.add_subparsers(dest="deliver_command", required=True)
    prepare_delivery = deliver_sub.add_parser("prepare")
    _project_arg(prepare_delivery)
    prepare_delivery.add_argument("--candidate", type=Path, required=True)
    prepare_delivery.add_argument("--master", type=Path, required=True)
    prepare_delivery.add_argument("--dependency", action="append", default=[])
    prepare_delivery.add_argument("--model", default="small")
    validate_delivery = deliver_sub.add_parser("validate")
    _project_arg(validate_delivery)
    approve_delivery = deliver_sub.add_parser("approve")
    _project_arg(approve_delivery)
    approve_delivery.add_argument("--actor", required=True)
    approve_delivery.add_argument("--reason", required=True)

    migrate = sub.add_parser("migrate-timeline")
    migrate_sub = migrate.add_subparsers(dest="migration_command", required=True)
    for operation in ("inspect", "plan", "apply", "validate", "activate", "rollback"):
        item = migrate_sub.add_parser(operation)
        _project_arg(item)
        item.add_argument("--edl", type=Path, required=True)
        if operation in {"apply", "validate", "activate", "rollback"}:
            item.add_argument("--actor", required=True)
            item.add_argument("--reason", required=True)
        if operation == "activate":
            item.add_argument("--confirm-unknown-approvals", action="store_true")

    cleanup = sub.add_parser("cleanup")
    _add_cleanup_subparsers(cleanup)

    editlog = sub.add_parser("editlog")
    editlog_sub = editlog.add_subparsers(dest="editlog_command", required=True)
    refresh = editlog_sub.add_parser("refresh")
    refresh.add_argument("--project", type=Path, default=None)
    refresh.add_argument("--raw-dir", type=Path, dest="raw_dir", default=None)
    refresh.add_argument("--video-id", default="")
    refresh.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _add_cleanup_subparsers(cleanup: argparse.ArgumentParser) -> None:
    cleanup_sub = cleanup.add_subparsers(dest="cleanup_command", required=True)
    for operation in ("verify", "bundle", "dry-run", "execute"):
        item = cleanup_sub.add_parser(operation)
        _project_arg(item)
        item.add_argument("--master-basename", required=True)
        if operation == "bundle":
            item.add_argument("--actor", required=True)
        if operation in {"dry-run", "execute"}:
            item.add_argument(
                "--full-paths",
                action="store_true",
                help="Include the full relative path list in JSON (debug).",
            )
        if operation == "dry-run":
            item.add_argument(
                "--session-id",
                default=None,
                help="Session id for optional --scratch-out inventory.",
            )
            item.add_argument(
                "--scratch-out",
                action="store_true",
                help="Write full inventory JSON under .avo/tmp/learndown/<session-id>/.",
            )
        if operation == "execute":
            item.add_argument(
                "--session-id",
                default=None,
                help="After successful cleanup, purge .avo/tmp/<kind>/<session-id>/ for all kinds.",
            )


def _emit(value: dict, *, as_json: bool = True) -> None:
    if as_json:
        print(
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
        )
    else:
        print(value)


def _pipeline(args: argparse.Namespace) -> int:
    from avo.timeline.command_registry import registry_document
    from avo.timeline.pipeline import TimelinePipeline

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    pipeline = TimelinePipeline(workspace)
    if args.pipeline_command == "run":
        result = pipeline.initialize()
    elif args.pipeline_command == "status":
        result = pipeline.status()
    elif args.pipeline_command == "verify-commands":
        result = registry_document()
    elif args.pipeline_command == "resume":
        result = pipeline.resume(
            actor=args.actor,
            reason=args.reason,
            recovery_event=args.recovery_event,
        )
    else:
        payload = _load_json(args.payload) if args.payload else {}
        payload.setdefault("actor", args.actor)
        payload.setdefault("reason", args.reason or f"pipeline stage {args.stage}")
        result = pipeline.advance(args.stage, **payload)
    _emit(result)
    return 0


def _timeline(args: argparse.Namespace) -> int:
    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    if args.timeline_command == "init":
        result = workspace.initialize()
    elif args.timeline_command == "status":
        result = workspace.status()
    elif args.timeline_command == "validate":
        result = workspace.validate()
    elif args.timeline_command == "resume":
        result = PipelineRunStore(workspace.pipeline_run_path).resume(
            actor=args.actor,
            reason=args.reason,
            recovery_event=args.recovery_event,
        )
    else:  # pragma: no cover - argparse protects this
        raise WorkspaceError(f"unknown timeline operation: {args.timeline_command}")
    _emit(result, as_json=True)
    return 0


def _parse_tuple(value: str, size: int) -> tuple[int, ...]:
    try:
        result = tuple(int(item.strip()) for item in value.split(":"))
    except ValueError as exc:
        raise ValueError(f"invalid numeric tuple: {value}") from exc
    if len(result) != size:
        raise ValueError(f"expected {size} colon-separated integers: {value}")
    return result


def _sync(args: argparse.Namespace) -> int:
    from avo.adapters.media.ffprobe import FfprobeMediaAdapter
    from avo.timeline.sync_service import SyncService

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    if workspace.authority != "canonical":
        workspace.initialize()
    service = SyncService(workspace)
    adapter = FfprobeMediaAdapter()
    if args.sync_command == "inventory":
        result = adapter.inventory(args.source)
        run = PipelineRunStore(workspace.pipeline_run_path)
        state = run.load()
        if (
            state["mainState"] == PipelineState.INTAKE.value
            and state["sideState"] is None
        ):
            run.advance(
                PipelineState.SOURCES_READY,
                TransitionFacts(),
                actor="avo.sync",
                reason="raw inventory completed",
                active_refs={"rawInventory": result},
            )
    elif args.sync_command == "validate":
        result = service.validate_current()
    elif args.sync_command == "decide":
        result = service.decide(
            decision=args.decision,
            candidate_hash=args.candidate_sha256,
            evidence_bundle_hash=args.evidence_sha256,
            actor=args.actor,
            reason=args.reason,
        )
        run = PipelineRunStore(workspace.pipeline_run_path)
        state = run.load()
        if (
            args.decision == "approved"
            and state["mainState"] == PipelineState.SOURCES_READY.value
            and state["sideState"] is None
        ):
            run.advance(
                PipelineState.SYNC_READY,
                TransitionFacts(sync_ready=True),
                actor=args.actor,
                reason=args.reason,
                active_refs={"syncRevisionId": result["subject"]["revisionId"]},
            )
    else:
        if args.kind == "not-applicable":
            inventory = adapter.inventory(args.source)
            fingerprints = {
                item["sourceId"]: item["fingerprint"]["sha256"]
                for item in inventory["sources"]
            }
            result = service.author_not_applicable(
                raw_fingerprints=fingerprints, actor=args.actor, reason=args.reason
            )
        else:
            if args.picture is None or args.audio is None:
                raise ValueError("calibration requires --picture and --audio")
            picture_fp = adapter.fingerprint(args.picture)
            audio_fp = adapter.fingerprint(args.audio)
            picture = {
                "sourceId": "picture",
                "kind": "raw",
                "fingerprint": picture_fp,
                "stream": args.picture_stream,
            }
            audio = {
                "sourceId": "audio",
                "kind": "raw",
                "fingerprint": audio_fp,
                "stream": args.audio_stream,
                "channels": args.channel,
            }
            if args.kind == "constant-offset":
                samples = [_parse_tuple(item, 2) for item in args.sample]
                result = service.author_constant(
                    picture=picture,
                    audio=audio,
                    offset_ticks=args.offset_ms,
                    timebase={"num": 1, "den": 1000},
                    samples=samples,
                    tolerance_ticks=args.tolerance_ms,
                    actor=args.actor,
                    reason=args.reason,
                )
            elif args.kind == "linear-drift":
                samples = [_parse_tuple(item, 3) for item in args.sample]
                result = service.author_linear(
                    picture=picture,
                    audio=audio,
                    rate_ratio={"num": args.rate_num, "den": args.rate_den},
                    offset_ticks=args.offset_ms,
                    timebase={"num": 1, "den": 1000},
                    samples=samples,
                    tolerance_ticks=args.tolerance_ms,
                    actor=args.actor,
                    reason=args.reason,
                )
            else:
                points = [
                    dict(zip(("pictureTicks", "audioTicks"), _parse_tuple(item, 2)))
                    for item in args.control_point
                ]
                samples = [_parse_tuple(item, 3) for item in args.sample]
                result = service.author_piecewise(
                    picture=picture,
                    audio=audio,
                    control_points=points,
                    timebase={"num": 1, "den": 1000},
                    samples=samples,
                    tolerance_ticks=args.tolerance_ms,
                    actor=args.actor,
                    reason=args.reason,
                )
    _emit(result)
    return 0


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def _animation(args: argparse.Namespace) -> int:
    from avo.timeline.animation import AnimationService
    from avo.timeline.provider_animation import ProviderAnimationService

    if args.animation_command == "author":
        workspace = TimelineWorkspace.from_project(
            args.project, video_id=args.video_id or None
        )
        result = AnimationService(workspace).author(
            _load_json(args.strategy),
            actor=args.actor,
            reason=args.reason,
        )
    else:
        service = ProviderAnimationService(args.catalog, provider=args.provider)
        if args.animation_command == "propose":
            result = service.propose(
                _load_json(args.pattern),
                actor=args.actor,
                intent_reference=args.intent_reference,
            )
        elif args.animation_command == "decide":
            result = service.decide(
                args.proposal,
                decision=args.decision,
                actor=args.actor,
                reason=args.reason,
            )
        elif args.animation_command == "recommend":
            catalog = service.initialize()
            result = {
                "recommendations": AnimationService.recommend(
                    catalog,
                    _load_json(args.diagnosis),
                    evidence_sha256=args.evidence_sha256,
                ),
                "applied": False,
            }
        else:
            result = service.reject_recommendation(
                pattern_id=args.pattern_id,
                evidence_sha256=args.evidence_sha256,
                actor=args.actor,
                reason=args.reason,
            )
    _emit(result)
    return 0


def _tracks(args: argparse.Namespace) -> int:
    from avo.adapters.media.timeline_render import TimelineRenderAdapter
    from avo.timeline.projection import write_assembly_projection
    from avo.timeline.tracks import TracksService

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    service = TracksService(workspace)
    if args.tracks_command == "resolve":
        result = service.author(
            _load_json(args.snapshot),
            actor=args.actor,
            reason=args.reason,
        )
    elif args.tracks_command == "inspect":
        result = service.inspect()
    else:
        projection_path, manifest = write_assembly_projection(workspace)
        rendered = TimelineRenderAdapter().render(
            projection_path,
            args.output,
            profile=args.profile,
        )
        result = {"projection": manifest, "render": rendered}
    _emit(result)
    return 0


def _bmap(args: argparse.Namespace) -> int:
    from avo.timeline.bmap_service import BMapService

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    service = BMapService(workspace)
    if args.bmap_command in {"create", "revise"}:
        result = service.author(
            _load_json(args.snapshot),
            actor=args.actor,
            reason=args.reason,
        )
    elif args.bmap_command == "status":
        result = service.status()
    else:
        result = service.rebase(
            _load_json(args.mapped_ranges),
            actor=args.actor,
            reason=args.reason,
        )
    _emit(result)
    if args.bmap_command == "rebase" and result.get("blockers"):
        return 4
    return 0


def _cmap(args: argparse.Namespace) -> int:
    from avo.timeline.cmap_service import CMapService
    from avo.timeline.materialize import materialize_cut_proof
    from avo.timeline.projection import write_cmap_projection

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    if workspace.authority != "canonical":
        workspace.initialize()
    service = CMapService(workspace)
    if args.cmap_command == "create":
        result = service.author(
            _load_json(args.snapshot),
            actor=args.actor,
            reason=args.reason,
        )
        run = PipelineRunStore(workspace.pipeline_run_path)
        state = run.load()
        if (
            state["mainState"] == PipelineState.SYNC_READY.value
            and state["sideState"] is None
        ):
            run.advance(
                PipelineState.CMAP_DRAFT,
                TransitionFacts(),
                actor=args.actor,
                reason=args.reason,
                active_refs={
                    **state["activeRefs"],
                    "cmapRevisionId": result["revisionId"],
                },
            )
    elif args.cmap_command == "project":
        edl, manifest = write_cmap_projection(
            workspace,
            service.store.load(),
            revision_id=args.revision_id,
        )
        result = {"edlPath": str(edl), "projection": manifest}
    else:
        result = materialize_cut_proof(
            workspace=workspace,
            cmap_revision_id=args.revision_id,
            output_path=args.output,
            render_profile=args.profile,
        )
    _emit(result)
    return 0


def _parse_dependency(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        key, separator, digest = value.partition("=")
        if not separator or not key or len(digest) != 64:
            raise ValueError(f"dependency must be name=sha256: {value}")
        result[key] = digest
    return dict(sorted(result.items()))


def _parse_window(value: str) -> dict:
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"window must be start:end:reason: {value}")
    start, end = float(parts[0]), float(parts[1])
    if end <= start:
        raise ValueError(f"window end must be after start: {value}")
    return {"start": start, "end": end, "reason": parts[2]}


def _review(args: argparse.Namespace) -> int:
    from avo.adapters.qc.registry import CheckpointQcRegistry
    from avo.adapters.transcribe.candidate import CandidateTranscriptionAdapter
    from avo.adapters.understand.watch_skill import WatchSkillAdapter
    from avo.timeline.approval_service import ApprovalService
    from avo.timeline.review_runner import ReviewRunner
    from avo.timeline.store import now_iso

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    if args.review_command == "decide":
        result = ApprovalService(workspace).decide(
            decision=args.decision,
            revision_id=args.revision_id,
            review_path=args.review,
            materialization_path=args.materialization,
            actor=args.actor,
            reason=args.reason,
        )
        _emit(result)
        return 0

    dependencies = _parse_dependency(args.dependency)
    candidate = args.candidate
    if args.materialization:
        materialization = _load_json(args.materialization)
        candidate = candidate or Path(materialization["output"]["path"])
        lock = materialization["canonicalInputLock"]
        derived = {
            "cmap": lock["cmapRevisionHash"],
            "sync-map": lock["syncRevisionHash"],
            "cutOutput": materialization["output"]["sha256"],
        }
        if dependencies and dependencies != derived:
            raise ValueError("explicit dependencies disagree with materialization")
        dependencies = derived
    if candidate is None:
        raise ValueError("review run requires --candidate or --materialization")
    if not dependencies:
        raise ValueError(
            "review run requires exact --dependency values or --materialization"
        )

    run_store = PipelineRunStore(workspace.pipeline_run_path)
    state = run_store.load()
    if (
        args.checkpoint == "cut-proof"
        and state["mainState"] == PipelineState.CMAP_DRAFT.value
        and state["sideState"] is None
    ):
        state = run_store.advance(
            PipelineState.CUT_AI_REVIEW,
            TransitionFacts(),
            actor="avo.review",
            reason="starting exact cut-proof AI review",
            active_refs={**state["activeRefs"], "candidatePath": str(candidate)},
        )

    result = ReviewRunner(
        review_root=workspace.review_dir,
        transcription=CandidateTranscriptionAdapter(),
        watch=WatchSkillAdapter(),
        deterministic_qc=CheckpointQcRegistry(),
        workspace=workspace,
        clock=now_iso,
    ).run(
        checkpoint=args.checkpoint,
        candidate=candidate,
        dependencies=dependencies,
        render_profile=args.profile,
        risk_windows=[_parse_window(value) for value in args.window],
        terms=args.term,
        names=args.name,
    )
    if result["state"] in {"blocked", "needs-human-judgment"}:
        current = run_store.load()
        if current["sideState"] is None:
            side = (
                PipelineState.BLOCKED
                if result["state"] == "blocked"
                else PipelineState.NEEDS_HUMAN_JUDGMENT
            )
            run_store.enter_side_state(
                side,
                actor="avo.review",
                reason=result.get("blocker") or result["state"],
                blockers=[
                    {
                        "code": "AVO-TL-023",
                        "message": result.get("blocker") or result["state"],
                        "remediation": "resolve the review finding and resume explicitly",
                    }
                ],
            )
    _emit(result)
    return 4 if result["state"] == "blocked" else 0


def _migrate(args: argparse.Namespace) -> int:
    from avo.timeline.migration import MigrationService

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    service = MigrationService(workspace, args.edl)
    if args.migration_command in {"inspect", "plan"}:
        result = service.plan()
    elif args.migration_command == "apply":
        result = service.apply(actor=args.actor, reason=args.reason)
    elif args.migration_command == "validate":
        result = service.validate(actor=args.actor, reason=args.reason)
    elif args.migration_command == "activate":
        result = service.activate(
            actor=args.actor,
            reason=args.reason,
            confirm_unknown_approvals=args.confirm_unknown_approvals,
        )
    else:
        result = service.rollback(actor=args.actor, reason=args.reason)
    _emit(result)
    return 0


def _systemexit_errors(exc: SystemExit) -> list[str]:
    message = exc.code if isinstance(exc.code, str) else str(exc)
    return [line for line in str(message).splitlines() if line]


def _space_payload(
    *,
    pre_cleanup: int = 0,
    delete_bytes: int = 0,
    preserved_bytes: int = 0,
    freed_bytes: int | None = None,
) -> dict:
    return {
        "preCleanupProjectBytes": pre_cleanup,
        "deleteCandidateBytes": delete_bytes,
        "preservedBytes": preserved_bytes,
        "freedBytes": freed_bytes,
    }


def _emit_blocked_cleanup(
    *,
    verify_errors: list[str],
    session_id: str | None,
    raw_dir: Path,
    full_paths: bool,
) -> int:
    from avo.project_inventory import compact_cleanup_result

    _emit(
        compact_cleanup_result(
            status="blocked",
            verify_errors=verify_errors,
            session_id=session_id,
            raw_dir=raw_dir,
            full_paths=full_paths,
        )
    )
    return 3


def _compact_from_outcome(
    *,
    status: str,
    outcome,
    session_id: str | None,
    full_paths: bool,
    raw_dir: Path,
    scratch_report: str | None = None,
    scratch_meta: str | None = None,
) -> dict:
    from avo.project_inventory import compact_cleanup_result

    dry = status == "dry-run"
    return compact_cleanup_result(
        status=status,
        candidates=outcome.paths if dry else (),
        deleted=() if dry else outcome.paths,
        preserved_count=len(outcome.preserved.all_paths),
        leftover_candidates=outcome.leftover,
        space=_space_payload(
            pre_cleanup=outcome.pre_cleanup_project_bytes,
            delete_bytes=outcome.delete_candidate_bytes,
            preserved_bytes=outcome.preserved_bytes,
            freed_bytes=None if dry else outcome.delete_candidate_bytes,
        ),
        session_id=session_id,
        scratch_report=scratch_report,
        scratch_meta=scratch_meta,
        full_paths=full_paths,
        raw_dir=raw_dir,
    )


def _write_dry_run_scratch(
    raw_dir: Path, master_basename: str, session_id: str
) -> tuple[str, str]:
    from avo.project_inventory import build_inventory_report
    from avo.scratch import write_inventory_scratch

    report = build_inventory_report(raw_dir, master_basename)
    report_path, meta_path = write_inventory_scratch(session_id, report.to_dict())
    return str(report_path), str(meta_path)


def _purge_session_stderr(session_id: str | None) -> None:
    if not session_id:
        return
    from avo.scratch import ScratchError, purge_session_tmp

    try:
        purged = purge_session_tmp(session_id)
    except ScratchError:
        purged = False
    if purged:
        print(f"scratch purged: session {session_id}", file=sys.stderr)


def _cleanup(args: argparse.Namespace) -> int:
    from avo.project_inventory import (
        PreservedSetViolation,
        compact_cleanup_result,
        resolve_preserved_set,
        run_cleanup,
        verify_preserved_complete,
    )
    from avo.timeline.reconstruction import build_reconstruction_bundle

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    raw_dir = workspace.raw_dir
    session_id = getattr(args, "session_id", None)
    full_paths = bool(getattr(args, "full_paths", False))

    if args.cleanup_command == "bundle":
        result = build_reconstruction_bundle(
            workspace,
            master_basename=args.master_basename,
            actor=args.actor,
        )
        _emit(result)
        return 0

    if args.cleanup_command == "verify":
        errors = verify_preserved_complete(raw_dir, args.master_basename)
        preserved = resolve_preserved_set(raw_dir, args.master_basename)
        _emit(
            compact_cleanup_result(
                status="pass" if not errors else "blocked",
                preserved_count=len(preserved.all_paths),
                verify_errors=errors,
                space=_space_payload(preserved_bytes=0),
                raw_dir=raw_dir,
            )
        )
        return 0 if not errors else 3

    try:
        outcome = run_cleanup(
            raw_dir,
            args.master_basename,
            dry_run=args.cleanup_command == "dry-run",
            session_id=session_id,
            purge_session=False,
        )
    except PreservedSetViolation as exc:
        return _emit_blocked_cleanup(
            verify_errors=[str(exc)],
            session_id=session_id,
            raw_dir=raw_dir,
            full_paths=full_paths,
        )
    except SystemExit as exc:
        return _emit_blocked_cleanup(
            verify_errors=_systemexit_errors(exc),
            session_id=session_id,
            raw_dir=raw_dir,
            full_paths=full_paths,
        )

    scratch_report = scratch_meta = None
    if args.cleanup_command == "dry-run" and getattr(args, "scratch_out", False):
        if not session_id:
            print("error: --session-id required with --scratch-out", file=sys.stderr)
            return 1
        scratch_report, scratch_meta = _write_dry_run_scratch(
            raw_dir, args.master_basename, session_id
        )

    status = "dry-run" if args.cleanup_command == "dry-run" else "executed"
    _emit(
        _compact_from_outcome(
            status=status,
            outcome=outcome,
            session_id=session_id,
            full_paths=full_paths,
            raw_dir=raw_dir,
            scratch_report=scratch_report,
            scratch_meta=scratch_meta,
        )
    )
    if status == "executed":
        _purge_session_stderr(session_id)
    return 0


def _deliver(args: argparse.Namespace) -> int:
    from avo.adapters.qc.registry import CheckpointQcRegistry
    from avo.adapters.transcribe.candidate import CandidateTranscriptionAdapter
    from avo.adapters.understand.watch_skill import WatchSkillAdapter
    from avo.timeline.delivery import DeliveryService
    from avo.timeline.review_runner import ReviewRunner
    from avo.timeline.store import now_iso

    workspace = TimelineWorkspace.from_project(
        args.project, video_id=args.video_id or None
    )
    service = DeliveryService(workspace)
    if args.deliver_command == "validate":
        result = service.validate_current()
    elif args.deliver_command == "approve":
        result = service.approve(actor=args.actor, reason=args.reason)
    else:
        dependencies = _parse_dependency(args.dependency)
        if not dependencies:
            dependencies = workspace.active_dependency_snapshot()
        runner = ReviewRunner(
            review_root=workspace.review_dir,
            transcription=CandidateTranscriptionAdapter(),
            watch=WatchSkillAdapter(),
            deterministic_qc=CheckpointQcRegistry(),
            workspace=workspace,
            clock=now_iso,
        )
        result = service.prepare(
            candidate=args.candidate,
            master=args.master,
            dependencies=dependencies,
            review_runner=runner,
            transcript_options={"model": args.model},
        )
    _emit(result)
    return 0


def _editlog(args: argparse.Namespace) -> int:
    from avo.editlog import EditlogError, refresh_editlog, resolve_editlog_raw_dir

    if args.editlog_command != "refresh":
        raise ValueError(f"unhandled editlog command: {args.editlog_command}")
    try:
        raw_dir = resolve_editlog_raw_dir(project=args.project, raw_dir=args.raw_dir)
        result = refresh_editlog(raw_dir)
    except EditlogError as exc:
        payload = {
            "ok": False,
            "code": exc.code,
            "message": exc.message,
            "path": None,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 3
    _emit(result, as_json=True)
    return 0


def _run_cli(args: argparse.Namespace) -> int:
    handlers = {
        "pipeline": _pipeline,
        "timeline": _timeline,
        "sync": _sync,
        "cmap": _cmap,
        "bmap": _bmap,
        "tracks": _tracks,
        "animation": _animation,
        "review": _review,
        "deliver": _deliver,
        "migrate-timeline": _migrate,
        "cleanup": _cleanup,
        "editlog": _editlog,
    }
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError(f"unhandled command: {args.command}")
    return handler(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run_cli(args)
    except (
        WorkspaceError,
        StoreError,
        LifecycleError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "code": "AVO-TL-011",
                    "message": str(exc),
                    "remediation": "run timeline status/validate and resolve the reported dependency",
                    "blocking": True,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
