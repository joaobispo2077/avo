"""CLI-bridged MCP tools for ``avo.cli`` groups (tasks 007â€“008).

Registers 1:1 tools ``avo_<group>_<subcommand>`` that delegate in-process to
``avo.cli.main`` via :mod:`avo.mcp.bridge`. Covers core groups (task-007) and
remaining groups: bmap, cmap, review, deliver, migrate-timeline, cleanup
(task-008).

Destructive tools (``ToolSpec.destructive``) are gated via MRTR
``InputRequiredResult`` before the CLI bridge (FR-15 / task-004). Client
capabilities from MCP ``Context`` filter ``inputRequests`` (task-005).
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from avo.mcp import mrtr
from avo.mcp.bridge import run_bridged
from avo.mcp.registry import ToolSpec

_MUTATE_WARN = "WARNING: Mutates project/timeline state. "
_RENDER_WARN = "WARNING: May write render/output files under the project. "
_DESTRUCTIVE_WARN = "DESTRUCTIVE: Irreversible or high-impact operation â€” confirm intent before calling. "

# Groups bridged in task-007.
CORE_CLI_GROUPS: tuple[str, ...] = (
    "pipeline",
    "timeline",
    "sync",
    "animation",
    "tracks",
)

# Remaining groups bridged in task-008.
REMAINING_CLI_GROUPS: tuple[str, ...] = (
    "costs",
    "direction",
    "briefstart",
    "bmap",
    "cmap",
    "review",
    "deliver",
    "migrate-timeline",
    "cleanup",
    "editlog",
)

ALL_CLI_GROUPS: tuple[str, ...] = CORE_CLI_GROUPS + REMAINING_CLI_GROUPS


@dataclass(frozen=True)
class ParamSpec:
    """One MCP tool parameter (becomes a keyword-only function arg)."""

    name: str
    annotation: Any
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class BridgeToolDef:
    """Declarative bridge: ToolSpec metadata + CLI prefix + parameter schema."""

    spec: ToolSpec
    cli_prefix: tuple[str, ...]
    params: tuple[ParamSpec, ...]


def _project_params() -> tuple[ParamSpec, ...]:
    """Shared ``--project`` / ``--video-id`` / ``--json`` surface."""
    return (
        ParamSpec("project", str, required=True),
        ParamSpec("video_id", str | None, default=None),
        ParamSpec("as_json", bool, default=True),
    )


def _tool(
    name: str,
    group: str,
    subcommand: str,
    description: str,
    *,
    destructive: bool = False,
    extra_params: Sequence[ParamSpec] = (),
    include_project: bool = True,
) -> BridgeToolDef:
    """Build a bridge def."""
    cli_prefix = (group, subcommand)
    params = (
        (_project_params() + tuple(extra_params))
        if include_project
        else tuple(extra_params)
    )
    return BridgeToolDef(
        spec=ToolSpec(
            name=name,
            description=description,
            group=group,
            destructive=destructive,
            cli_argv_template=cli_prefix,
        ),
        cli_prefix=cli_prefix,
        params=params,
    )


def _core_bridge_defs() -> list[BridgeToolDef]:
    """Explicit map for pipeline / timeline / sync / animation / tracks."""
    motion_json = ParamSpec("as_json", bool, default=True)
    motion_context = (
        ParamSpec("project", str | None, default=None),
        ParamSpec("provider", str | None, default=None),
        motion_json,
    )
    return [
        # --- pipeline ---
        _tool(
            "avo_pipeline_run",
            "pipeline",
            "run",
            _MUTATE_WARN
            + "Initialize / run pipeline for a project (CLI: avo pipeline run).",
            destructive=True,
            extra_params=(
                ParamSpec("motion_engine", str | None, default=None),
                ParamSpec("new_request", bool, default=False),
                ParamSpec("cost_context", dict[str, Any] | None, default=None),
                ParamSpec("direction", str | None, default=None),
                ParamSpec("brief_context", str | None, default=None),
                ParamSpec("direction_reference", list[str] | None, default=None),
            ),
        ),
        _tool(
            "avo_pipeline_status",
            "pipeline",
            "status",
            "Show pipeline status for a project (CLI: avo pipeline status).",
        ),
        _tool(
            "avo_pipeline_verify_commands",
            "pipeline",
            "verify-commands",
            "Verify the pipeline command registry (CLI: avo pipeline verify-commands).",
        ),
        _tool(
            "avo_pipeline_resume",
            "pipeline",
            "resume",
            _MUTATE_WARN
            + "Resume a paused/failed pipeline (CLI: avo pipeline resume).",
            destructive=True,
            extra_params=(
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
                ParamSpec("recovery_event", str, required=True),
                ParamSpec("cost_context", dict[str, Any] | None, default=None),
            ),
        ),
        _tool(
            "avo_pipeline_stage",
            "pipeline",
            "stage",
            _MUTATE_WARN + "Advance the pipeline to a stage (CLI: avo pipeline stage).",
            destructive=True,
            extra_params=(
                ParamSpec("stage", str, required=True),
                ParamSpec("payload", str | None, default=None),
                ParamSpec("actor", str | None, default=None),
                ParamSpec("reason", str | None, default=None),
            ),
        ),
        # --- timeline ---
        _tool(
            "avo_timeline_init",
            "timeline",
            "init",
            _MUTATE_WARN + "Initialize timeline workspace (CLI: avo timeline init).",
            destructive=True,
        ),
        _tool(
            "avo_timeline_status",
            "timeline",
            "status",
            "Show timeline workspace status (CLI: avo timeline status).",
        ),
        _tool(
            "avo_timeline_validate",
            "timeline",
            "validate",
            "Validate timeline workspace (CLI: avo timeline validate).",
        ),
        _tool(
            "avo_timeline_resume",
            "timeline",
            "resume",
            _MUTATE_WARN + "Resume timeline lifecycle (CLI: avo timeline resume).",
            destructive=True,
            extra_params=(
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
                ParamSpec("recovery_event", str, required=True),
            ),
        ),
        # --- sync ---
        _tool(
            "avo_sync_inventory",
            "sync",
            "inventory",
            _MUTATE_WARN + "Record sync source inventory (CLI: avo sync inventory).",
            destructive=True,
            extra_params=(ParamSpec("source", list[str], required=True),),
        ),
        _tool(
            "avo_sync_calibrate",
            "sync",
            "calibrate",
            _MUTATE_WARN
            + "Write a sync calibration candidate (CLI: avo sync calibrate).",
            destructive=True,
            extra_params=(
                ParamSpec("kind", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
                ParamSpec("picture", str | None, default=None),
                ParamSpec("audio", str | None, default=None),
                ParamSpec("picture_stream", str | None, default=None),
                ParamSpec("audio_stream", str | None, default=None),
                ParamSpec("channel", list[int] | None, default=None),
                ParamSpec("offset_ms", int | None, default=None),
                ParamSpec("tolerance_ms", int | None, default=None),
                ParamSpec("sample", list[str] | None, default=None),
                ParamSpec("control_point", list[str] | None, default=None),
                ParamSpec("rate_num", int | None, default=None),
                ParamSpec("rate_den", int | None, default=None),
                ParamSpec("source", list[str] | None, default=None),
            ),
        ),
        _tool(
            "avo_sync_validate",
            "sync",
            "validate",
            "Validate sync calibration state (CLI: avo sync validate).",
        ),
        _tool(
            "avo_sync_decide",
            "sync",
            "decide",
            _MUTATE_WARN + "Record a sync decision (CLI: avo sync decide).",
            destructive=True,
            extra_params=(
                ParamSpec("decision", str, required=True),
                ParamSpec("candidate_sha256", str, required=True),
                ParamSpec("evidence_sha256", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        # --- animation ---
        _tool(
            "avo_animation_engine_show",
            "animation",
            "engine-show",
            "Inspect saved motion-engine preferences, effective choice, and "
            "readiness without writing settings, installing runtimes, or rendering "
            "(CLI: avo cli animation engine-show).",
            include_project=False,
            extra_params=(
                *motion_context,
                ParamSpec("motion_engine", str | None, default=None),
            ),
        ),
        _tool(
            "avo_animation_engine_set",
            "animation",
            "engine-set",
            "WARNING: Saves a motion-engine preference at the selected global, "
            "provider, or project scope. Choose hyperframes, remotion, or "
            "code-drawn; saving does not install a runtime or render "
            "(CLI: avo cli animation engine-set).",
            include_project=False,
            extra_params=(
                *motion_context,
                ParamSpec("scope", str, required=True),
                ParamSpec("engine", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_engine_reset",
            "animation",
            "engine-reset",
            "WARNING: Resets only the selected global, provider, or project "
            "motion-engine preference to restore inheritance; preserves unrelated "
            "settings and does not install a runtime or render "
            "(CLI: avo cli animation engine-reset).",
            include_project=False,
            extra_params=(
                *motion_context,
                ParamSpec("scope", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_runtime_install",
            "animation",
            "runtime-install",
            "WARNING: Uses network access to download the matched code-drawn "
            "browser runtime and optional local brush dependency. Writes the "
            "selected runtime cache; does not render or change engine preferences "
            "(CLI: avo cli animation runtime-install).",
            include_project=False,
            extra_params=(
                ParamSpec("engine", Literal["code-drawn"], required=True),
                ParamSpec("brush", bool, default=False),
                motion_json,
            ),
        ),
        _tool(
            "avo_animation_code_drawn_scaffold",
            "animation",
            "code-drawn-scaffold",
            "WARNING: Writes generic editable code-drawn source and project "
            "documents to a new external destination without overwriting it. "
            "No downloads or timeline changes (CLI: avo cli animation code-drawn-scaffold).",
            include_project=False,
            extra_params=(
                ParamSpec("destination", str, required=True),
                ParamSpec("route", Literal["canvas", "svg", "brush"], required=True),
                ParamSpec("width", int, required=True),
                ParamSpec("height", int, required=True),
                ParamSpec("fps", str, required=True),
                ParamSpec("frames", int, required=True),
                ParamSpec(
                    "background", Literal["opaque", "transparent"], default="opaque"
                ),
                ParamSpec("background_color", str | None, default=None),
                motion_json,
            ),
        ),
        _tool(
            "avo_animation_code_drawn_check",
            "animation",
            "code-drawn-check",
            "Check a local composition, selected runtime, and independent seeking; "
            "optionally writes a new immutable standalone output lock. No downloads "
            "or editorial approval changes (CLI: avo cli animation code-drawn-check).",
            include_project=False,
            extra_params=(
                ParamSpec("composition", str, required=True),
                ParamSpec("input_lock", str | None, default=None),
                ParamSpec("output_lock", str | None, default=None),
                motion_json,
            ),
        ),
        _tool(
            "avo_animation_code_drawn_snapshot",
            "animation",
            "code-drawn-snapshot",
            "WARNING: Writes a lossless frame at the declared integer frame index "
            "to a new external output path. No downloads, canonical proof, or "
            "approval changes (CLI: avo cli animation code-drawn-snapshot).",
            include_project=False,
            extra_params=(
                ParamSpec("composition", str, required=True),
                ParamSpec("frame", int, required=True),
                ParamSpec("output", str, required=True),
                ParamSpec("input_lock", str | None, default=None),
                motion_json,
            ),
        ),
        _tool(
            "avo_animation_code_drawn_render",
            "animation",
            "code-drawn-render",
            "WARNING: Writes verified silent generated graphics and their receipt "
            "at new external output paths from the supplied composition and lock. "
            "No downloads or creator approval; this is not a canonical footage proof "
            "(CLI: avo cli animation code-drawn-render).",
            include_project=False,
            extra_params=(
                ParamSpec("composition", str, required=True),
                ParamSpec("input_lock", str, required=True),
                ParamSpec("output", str, required=True),
                motion_json,
            ),
        ),
        _tool(
            "avo_animation_code_drawn_review",
            "animation",
            "code-drawn-review",
            "Create exact-candidate decoded frames, contact sheets, small views and requested transition/loop strips from verified code-drawn sources; writes pending visual evidence with no creator approval (CLI: avo cli animation code-drawn-review).",
            include_project=False,
            extra_params=(
                ParamSpec("candidate", str, required=True),
                ParamSpec("source_receipt", list[str], required=True),
                ParamSpec("output", str, required=True),
                ParamSpec("project", str | None, default=None),
                ParamSpec("video_id", str | None, default=None),
                ParamSpec("render_profile", str, default="code-drawn"),
                ParamSpec("materialization", str | None, default=None),
                ParamSpec("dependency", list[str] | None, default=None),
                ParamSpec("sample_frame", list[int] | None, default=None),
                ParamSpec("transition", list[str] | None, default=None),
                ParamSpec("loop", bool, default=False),
                motion_json,
            ),
        ),
        _tool(
            "avo_animation_materialize",
            "animation",
            "materialize",
            "Generate and admit the recorded code-drawn instance from current canonical source/Tracks bindings; writes a new asset without changing creator approval or pipeline stage (CLI: avo cli animation materialize).",
            extra_params=(
                ParamSpec("instance_id", str, required=True),
                ParamSpec("output", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_author",
            "animation",
            "author",
            _MUTATE_WARN
            + "Author animation from a strategy file (CLI: avo animation author).",
            destructive=True,
            extra_params=(
                ParamSpec("strategy", str, required=True),
                ParamSpec("motion_engine", str | None, default=None),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_propose",
            "animation",
            "propose",
            _MUTATE_WARN + "Propose an animation pattern (CLI: avo animation propose).",
            destructive=True,
            include_project=False,
            extra_params=(
                ParamSpec("catalog", str, required=True),
                ParamSpec("provider", str, required=True),
                ParamSpec("pattern", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("intent_reference", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_decide",
            "animation",
            "decide",
            _MUTATE_WARN
            + "Approve or reject an animation proposal (CLI: avo animation decide).",
            destructive=True,
            include_project=False,
            extra_params=(
                ParamSpec("catalog", str, required=True),
                ParamSpec("provider", str, required=True),
                ParamSpec("proposal", str, required=True),
                ParamSpec("decision", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_recommend",
            "animation",
            "recommend",
            "Recommend animation patterns from diagnosis (CLI: avo animation recommend).",
            include_project=False,
            extra_params=(
                ParamSpec("catalog", str, required=True),
                ParamSpec("provider", str, required=True),
                ParamSpec("diagnosis", str, required=True),
                ParamSpec("evidence_sha256", str, required=True),
            ),
        ),
        _tool(
            "avo_animation_reject_recommendation",
            "animation",
            "reject-recommendation",
            _MUTATE_WARN
            + "Reject an animation recommendation (CLI: avo animation reject-recommendation).",
            destructive=True,
            include_project=False,
            extra_params=(
                ParamSpec("catalog", str, required=True),
                ParamSpec("provider", str, required=True),
                ParamSpec("pattern_id", str, required=True),
                ParamSpec("evidence_sha256", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        # --- tracks ---
        _tool(
            "avo_tracks_resolve",
            "tracks",
            "resolve",
            _MUTATE_WARN + "Resolve tracks from a snapshot (CLI: avo tracks resolve).",
            destructive=True,
            extra_params=(
                ParamSpec("snapshot", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        _tool(
            "avo_tracks_inspect",
            "tracks",
            "inspect",
            "Inspect resolved tracks (CLI: avo tracks inspect).",
        ),
        _tool(
            "avo_tracks_render",
            "tracks",
            "render",
            _RENDER_WARN + "Render tracks to an output path (CLI: avo tracks render).",
            destructive=True,
            extra_params=(
                ParamSpec("output", str, required=True),
                ParamSpec("profile", str | None, default=None),
                ParamSpec("render_contract", str, required=True),
                ParamSpec("fidelity_policy", str | None, default=None),
            ),
        ),
    ]


def _remaining_bridge_defs() -> list[BridgeToolDef]:
    """Explicit map for bmap / cmap / review / deliver / migrate-timeline / cleanup."""
    migrate_edl = (ParamSpec("edl", str, required=True),)
    migrate_actor_reason = (
        ParamSpec("actor", str, required=True),
        ParamSpec("reason", str, required=True),
    )
    return [
        # --- bmap ---
        _tool(
            "avo_bmap_create",
            "bmap",
            "create",
            _MUTATE_WARN + "Create a B-map revision (CLI: avo bmap create).",
            destructive=True,
            extra_params=(
                ParamSpec("snapshot", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        _tool(
            "avo_bmap_revise",
            "bmap",
            "revise",
            _MUTATE_WARN + "Revise a B-map from a snapshot (CLI: avo bmap revise).",
            destructive=True,
            extra_params=(
                ParamSpec("snapshot", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        _tool(
            "avo_bmap_status",
            "bmap",
            "status",
            "Show B-map status (CLI: avo bmap status).",
        ),
        _tool(
            "avo_bmap_rebase",
            "bmap",
            "rebase",
            _MUTATE_WARN + "Rebase B-map mapped ranges (CLI: avo bmap rebase).",
            destructive=True,
            extra_params=(
                ParamSpec("mapped_ranges", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        # --- cmap ---
        _tool(
            "avo_cmap_create",
            "cmap",
            "create",
            _MUTATE_WARN + "Create a C-map revision (CLI: avo cmap create).",
            destructive=True,
            extra_params=(
                ParamSpec("snapshot", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        _tool(
            "avo_cmap_project",
            "cmap",
            "project",
            "Project a C-map revision to EDL/manifest (CLI: avo cmap project).",
            extra_params=(ParamSpec("revision_id", str, required=True),),
        ),
        _tool(
            "avo_cmap_render",
            "cmap",
            "render",
            _RENDER_WARN + "Render a C-map revision (CLI: avo cmap render).",
            destructive=True,
            extra_params=(
                ParamSpec("revision_id", str, required=True),
                ParamSpec("output", str, required=True),
                ParamSpec("profile", str | None, default=None),
            ),
        ),
        # --- review ---
        # Handlers import ReviewRunner lazily via CLI; no watch-skill at import/registration.
        _tool(
            "avo_review_run",
            "review",
            "run",
            "Run an orchestrator review checkpoint (CLI: avo review run). "
            "Does not replace watch-skill verify.",
            extra_params=(
                ParamSpec("checkpoint", str | None, default=None),
                ParamSpec("candidate", str | None, default=None),
                ParamSpec("materialization", str | None, default=None),
                ParamSpec("dependency", list[str] | None, default=None),
                ParamSpec("window", list[str] | None, default=None),
                ParamSpec("term", list[str] | None, default=None),
                ParamSpec("name", list[str] | None, default=None),
                ParamSpec("profile", str | None, default=None),
            ),
        ),
        _tool(
            "avo_review_decide",
            "review",
            "decide",
            _MUTATE_WARN + "Record a review decision (CLI: avo review decide).",
            destructive=True,
            extra_params=(
                ParamSpec("decision", str, required=True),
                ParamSpec("revision_id", str, required=True),
                ParamSpec("review", str, required=True),
                ParamSpec("materialization", str, required=True),
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        # --- deliver ---
        _tool(
            "avo_deliver_prepare",
            "deliver",
            "prepare",
            _MUTATE_WARN + "Prepare delivery artifacts (CLI: avo deliver prepare).",
            destructive=True,
            extra_params=(
                ParamSpec("candidate", str | None, default=None),
                ParamSpec("materialization", str, required=True),
                ParamSpec("master", str, required=True),
                ParamSpec("dependency", list[str] | None, default=None),
                ParamSpec("model", str | None, default=None),
                ParamSpec("motion_review", str | None, default=None),
            ),
        ),
        _tool(
            "avo_deliver_validate",
            "deliver",
            "validate",
            "Validate delivery readiness (CLI: avo deliver validate).",
        ),
        _tool(
            "avo_deliver_approve",
            "deliver",
            "approve",
            _MUTATE_WARN + "Approve delivery (CLI: avo deliver approve).",
            destructive=True,
            extra_params=(
                ParamSpec("actor", str, required=True),
                ParamSpec("reason", str, required=True),
            ),
        ),
        # --- migrate-timeline ---
        _tool(
            "avo_migrate_timeline_inspect",
            "migrate-timeline",
            "inspect",
            "Inspect a timeline migration EDL (CLI: avo migrate-timeline inspect).",
            extra_params=migrate_edl,
        ),
        _tool(
            "avo_migrate_timeline_plan",
            "migrate-timeline",
            "plan",
            "Plan a timeline migration (CLI: avo migrate-timeline plan).",
            extra_params=migrate_edl,
        ),
        _tool(
            "avo_migrate_timeline_apply",
            "migrate-timeline",
            "apply",
            _MUTATE_WARN
            + "Apply a timeline migration (CLI: avo migrate-timeline apply).",
            destructive=True,
            extra_params=migrate_edl + migrate_actor_reason,
        ),
        _tool(
            "avo_migrate_timeline_validate",
            "migrate-timeline",
            "validate",
            "Validate a timeline migration (CLI: avo migrate-timeline validate).",
            extra_params=migrate_edl + migrate_actor_reason,
        ),
        _tool(
            "avo_migrate_timeline_activate",
            "migrate-timeline",
            "activate",
            _DESTRUCTIVE_WARN + "Activate a migrated timeline as the active workspace "
            "(CLI: avo migrate-timeline activate).",
            destructive=True,
            extra_params=migrate_edl
            + migrate_actor_reason
            + (ParamSpec("confirm_unknown_approvals", bool, default=False),),
        ),
        _tool(
            "avo_migrate_timeline_rollback",
            "migrate-timeline",
            "rollback",
            _DESTRUCTIVE_WARN
            + "Roll back a timeline migration (CLI: avo migrate-timeline rollback).",
            destructive=True,
            extra_params=migrate_edl + migrate_actor_reason,
        ),
        # --- cleanup ---
        _tool(
            "avo_cleanup_verify",
            "cleanup",
            "verify",
            "Verify cleanup prerequisites. Returns compact JSON (status, "
            "verifyErrors, counts/sample) â€” not every path. Use built-in CLI/MCP; "
            "do not write .avo/tmp/**/execute_*.py walk/delete scripts. "
            "(CLI: avo cleanup verify).",
            extra_params=(ParamSpec("master_basename", str, required=True),),
        ),
        _tool(
            "avo_cleanup_bundle",
            "cleanup",
            "bundle",
            _MUTATE_WARN + "Build a cleanup bundle (CLI: avo cleanup bundle).",
            destructive=True,
            extra_params=(
                ParamSpec("master_basename", str, required=True),
                ParamSpec("actor", str, required=True),
            ),
        ),
        _tool(
            "avo_cleanup_dry_run",
            "cleanup",
            "dry-run",
            "Dry-run cleanup without deleting files. Returns compact JSON "
            "(candidateCount, leftoverCandidates, candidateSample â‰¤50). Full path "
            "lists live in optional CLI scratch (--session-id --scratch-out). "
            "Do not write .avo/tmp/**/execute_*.py walk/delete scripts. "
            "(CLI: avo cleanup dry-run).",
            extra_params=(ParamSpec("master_basename", str, required=True),),
        ),
        _tool(
            "avo_cleanup_execute",
            "cleanup",
            "execute",
            _DESTRUCTIVE_WARN + "Permanently delete non-preserved run artifacts. "
            "Returns compact JSON (deletedCount, deletedSample, space.freedBytes) "
            "before session tmp purge. Prefer dry-run first. Do not write "
            ".avo/tmp/**/execute_*.py walk/delete scripts. "
            "(CLI: avo cleanup execute).",
            destructive=True,
            extra_params=(
                ParamSpec("master_basename", str, required=True),
                ParamSpec("session_id", str | None, default=None),
            ),
        ),
        _tool(
            "avo_editlog_refresh",
            "editlog",
            "refresh",
            "Refresh footage-root EDITLOG.md from canonical JSON. Rewrites only "
            "the marked AVO digest; append rationale under Human notes. Do not "
            "walk edit/ to hand-write the digest. (CLI: avo editlog refresh).",
            include_project=False,
            extra_params=(
                ParamSpec("project", str | None, default=None),
                ParamSpec("raw_dir", str | None, default=None),
                ParamSpec("video_id", str | None, default=None),
                ParamSpec("as_json", bool, default=True),
            ),
        ),
    ]


def _creative_params(group, operation):
    params = [ParamSpec("as_json", bool, default=True)]
    params.append(
        ParamSpec("project", str, required=True)
        if group == "briefstart"
        else ParamSpec("provider", str | None, default=None)
    )
    if operation in {"propose", "decide"}:
        params.append(ParamSpec("request", str, required=True))
    elif operation == "show":
        params.append(ParamSpec("ref", str, required=group == "direction"))
        if group == "direction":
            params.append(ParamSpec("check_sources", bool, default=False))
    elif operation == "prepare":
        params.extend(_creative_prepare_params(group))
    return tuple(params)


def _creative_prepare_params(group):
    if group == "direction":
        return (
            ParamSpec("profile_id", str, required=True),
            ParamSpec("entry", list[str] | None, default=None),
            ParamSpec("refresh_from", str | None, default=None),
        )
    return (
        ParamSpec("direction", str | None, default=None),
        ParamSpec("context", str | None, default=None),
        ParamSpec("reference", list[str] | None, default=None),
    )


def _creative_bridge_defs():
    definitions = []
    for group in ("direction", "briefstart"):
        operations = (
            ("catalog", "prepare", "propose", "decide", "show")
            if group == "direction"
            else ("prepare", "propose", "decide", "show")
        )
        for operation in operations:
            action = (
                "Writes reviewable authorial documents. "
                if operation in {"prepare", "propose"}
                else ""
            )
            if operation == "decide":
                action = "Records an exact human decision; confirmation binds request content. "
            definitions.append(
                _tool(
                    f"avo_{group}_{operation}",
                    group,
                    operation,
                    action
                    + f"Delegate {group} {operation} to the shared native CLI; no media or model job.",
                    destructive=operation == "decide",
                    include_project=False,
                    extra_params=_creative_params(group, operation),
                )
            )
    return definitions


def _all_bridge_defs() -> list[BridgeToolDef]:
    """Core (task-007) + remaining (task-008) bridge defs."""
    return (
        _core_bridge_defs()
        + _remaining_bridge_defs()
        + _creative_bridge_defs()
        + _cost_bridge_defs()
    )


def _cost_bridge_defs():
    optional_source = (
        ParamSpec("session_id", str | None),
        ParamSpec("format", str, default="normalized"),
    )
    files = (ParamSpec("file", str, required=True),)
    operations = {
        "context": (ParamSpec("descriptor", dict[str, Any], required=True),),
        "observe": (ParamSpec("packet", dict[str, Any], required=True),),
        "transition": (ParamSpec("request", dict[str, Any], required=True),),
        "estimate": (ParamSpec("request", dict[str, Any], required=True),),
        "reconcile": (ParamSpec("reconciliation", dict[str, Any], required=True),),
        "report": (
            ParamSpec("history", bool, default=False),
            ParamSpec("phase", str | None),
            ParamSpec("provider", str | None),
            ParamSpec("snapshot_id", str | None),
            ParamSpec("trends", bool, default=False),
        ),
        "capabilities": (ParamSpec("agent", str | None),),
        "bind": tuple(
            ParamSpec(name, str, required=True)
            for name in ("source", "agent", "session_id", "boundary")
        )
        + (
            ParamSpec("format", str, default="normalized"),
            ParamSpec("run_id", str | None),
            ParamSpec("phase", str | None),
        ),
        "collect": (ParamSpec("binding_id", str | None),),
        "import": files + optional_source,
        "report-manual": (
            ParamSpec("file", str | None, default=None),
            ParamSpec("request", dict[str, Any] | None, default=None),
            ParamSpec("participation_fact_id", str | None, default=None),
            ParamSpec("operation_id", str | None, default=None),
        ),
        "snapshot": (ParamSpec("stage", str, default="draft"),),
        "price": files,
        "correct": files,
        "revalue": files,
        "close-binding": (
            ParamSpec("binding_id", str, required=True),
            ParamSpec("end_boundary", str, required=True),
        ),
        "fork": (ParamSpec("new_video_id", str, required=True),),
    }
    return [
        _tool(
            "avo_costs_" + operation.replace("-", "_"),
            "costs",
            operation,
            "Recorded local usage and cost; incomplete sources remain visible.",
            destructive=operation not in {"report", "capabilities"},
            extra_params=params,
            include_project=operation != "capabilities",
        )
        for operation, params in operations.items()
    ]


def core_bridge_defs() -> list[BridgeToolDef]:
    """Return declarative defs for core CLI groups (task-007)."""
    return list(_core_bridge_defs())


def remaining_bridge_defs() -> list[BridgeToolDef]:
    """Return declarative defs for remaining CLI groups (task-008)."""
    return _remaining_bridge_defs() + _creative_bridge_defs() + _cost_bridge_defs()


def all_bridge_defs() -> list[BridgeToolDef]:
    """Return all phase-1 CLI bridge defs."""
    return list(_all_bridge_defs())


def core_cli_tool_specs() -> list[ToolSpec]:
    """ToolSpec catalog entries for core bridged CLI tools."""
    return [defn.spec for defn in _core_bridge_defs()]


def remaining_cli_tool_specs() -> list[ToolSpec]:
    """ToolSpec catalog entries for remaining bridged CLI tools (task-008)."""
    return [defn.spec for defn in remaining_bridge_defs()]


def all_cli_tool_specs() -> list[ToolSpec]:
    """ToolSpec catalog entries for all bridged CLI tools."""
    return [defn.spec for defn in _all_bridge_defs()]


def _context_annotation() -> Any:
    """Return MCP ``Context`` when the optional extra is installed, else ``Any``."""
    try:
        from mcp.server.mcpserver.context import Context

        return Context
    except ImportError:
        return Any


def _handler_return_annotation() -> Any:
    """``dict`` result, or union with SDK ``InputRequiredResult`` when available."""
    try:
        from mcp.types import InputRequiredResult

        return dict[str, Any] | InputRequiredResult
    except ImportError:
        return dict[str, Any]


def _run_destructive_gated(defn: BridgeToolDef, kwargs: dict[str, Any]) -> Any:
    """MRTR gate then CLI bridge for ``destructive=True`` tools."""
    ctx = kwargs.pop("ctx", None)
    request_state, input_responses = mrtr.extract_mrtr_fields(kwargs, ctx=ctx)
    bridge_args = mrtr.bridge_kwargs_from_tool_kwargs(kwargs)
    client_capabilities = mrtr.extract_client_capabilities(ctx)
    try:
        gate_args = _decision_gate_args(defn, bridge_args)
    except (OSError, ValueError) as exc:
        return _bridge_gate_error(exc)

    decision = mrtr.evaluate_destructive_gate(
        tool=defn.spec.name,
        args=gate_args,
        request_state=request_state,
        input_responses=input_responses,
        client_capabilities=client_capabilities,
        # Live Context path: honor declared caps (including empty/None).
        # Direct unit calls without ctx keep capability-unaware defaults.
        capabilities_provided=ctx is not None,
    )
    if decision.outcome is mrtr.GateOutcome.INPUT_REQUIRED:
        return decision.result
    if decision.outcome is mrtr.GateOutcome.REJECT:
        return mrtr.gate_error_envelope(
            decision.error_message or "destructive tool confirmation rejected"
        )
    try:
        if _decision_gate_args(defn, bridge_args) != gate_args:
            return mrtr.gate_error_envelope(
                "Decision document changed during confirmation"
            )
    except (OSError, ValueError) as exc:
        return _bridge_gate_error(exc)
    if "_decisionDocumentSha256" in gate_args:
        bridge_args = {
            **bridge_args,
            "request_sha256": gate_args["_decisionDocumentSha256"],
        }
    return run_bridged(defn.cli_prefix, bridge_args).to_dict()


def _bridge_gate_error(exc):
    from avo.cost_store import CostError

    if isinstance(exc, CostError):
        import json

        from avo.mcp.bridge import BridgeResult

        error = json.dumps({"status": "invalid-input", "message": str(exc)})
        return BridgeResult(False, 2, "", error).to_dict()
    return mrtr.gate_error_envelope(str(exc))


def _decision_gate_args(defn, bridge_args):
    from avo.mcp.bridge import normalize_cost_arguments

    normalize_cost_arguments(defn.cli_prefix, bridge_args)
    if defn.cli_prefix not in {("direction", "decide"), ("briefstart", "decide")}:
        return bridge_args
    with Path(bridge_args["request"]).expanduser().open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Decision request exceeds 2 MiB")
    return {**bridge_args, "_decisionDocumentSha256": hashlib.sha256(raw).hexdigest()}


def _make_handler(defn: BridgeToolDef) -> Callable[..., Any]:
    """Build a keyword-only handler whose signature drives the MCP input schema.

    Destructive tools inject optional MCP ``Context`` (for ``input_responses`` /
    ``request_state``) and may return ``InputRequiredResult`` instead of the
    bridge envelope.
    """
    return_ann = _handler_return_annotation()

    if defn.spec.destructive:

        def handler(**kwargs: Any) -> Any:
            return _run_destructive_gated(defn, dict(kwargs))

    else:

        def handler(**kwargs: Any) -> Any:
            return run_bridged(defn.cli_prefix, kwargs).to_dict()

    parameters: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {"return": return_ann}
    for param in defn.params:
        annotations[param.name] = param.annotation
        if param.required:
            parameters.append(
                inspect.Parameter(
                    param.name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=param.annotation,
                )
            )
        else:
            parameters.append(
                inspect.Parameter(
                    param.name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=param.default,
                    annotation=param.annotation,
                )
            )

    if defn.spec.destructive:
        ctx_ann = _context_annotation()
        annotations["ctx"] = ctx_ann
        parameters.append(
            inspect.Parameter(
                "ctx",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=ctx_ann,
            )
        )

    handler.__name__ = defn.spec.name
    handler.__qualname__ = defn.spec.name
    handler.__doc__ = defn.spec.description
    handler.__annotations__ = annotations
    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters,
        return_annotation=return_ann,
    )
    return handler


def _bridge_defs_for_specs(
    specs: list[ToolSpec] | None,
) -> list[BridgeToolDef]:
    """Resolve BridgeToolDefs for registration (all bridged, or a filtered subset)."""
    catalog = _all_bridge_defs()
    if specs is None:
        return catalog
    if not specs:
        return []
    by_name = {defn.spec.name: defn for defn in catalog}
    resolved: list[BridgeToolDef] = []
    missing: list[str] = []
    for spec in specs:
        defn = by_name.get(spec.name)
        if defn is None:
            missing.append(spec.name)
            continue
        resolved.append(defn)
    if missing:
        raise NotImplementedError(
            "CLI bridge defs unavailable for: " + ", ".join(missing)
        )
    return resolved


def register_cli_tools(
    server: Any,
    *,
    specs: list[ToolSpec] | None = None,
) -> list[ToolSpec]:
    """Register bridged CLI tools on ``server``.

    When ``specs`` is None, registers all phase-1 CLI tools (core + remaining).
    Pass an empty list to register nothing. Pass an explicit subset of known
    ToolSpecs to register only those. Unknown names raise ``NotImplementedError``.

    Returns:
        The list of ToolSpecs that were registered.
    """
    defs = _bridge_defs_for_specs(specs)
    registered: list[ToolSpec] = []
    for defn in defs:
        handler = _make_handler(defn)
        server.tool(name=defn.spec.name, description=defn.spec.description)(handler)
        registered.append(defn.spec)
    return registered
