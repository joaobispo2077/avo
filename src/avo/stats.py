"""Local-only aggregate metrics for AVO — session recording and ``/avo.stats`` display.

No network I/O. Reads and writes ``.avo/state.json`` via atomic save.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avo import avo_state
from avo.paths import config_path
from avo.project_inventory import resolve_preserved_set
from avo.telemetry import human_bytes, human_duration

try:
    from avo.render import media_duration
except ImportError:
    try:
        from avo.render import media_duration  # type: ignore
    except ImportError:
        media_duration = None  # type: ignore

ESTIMATION_MODEL = "duration-factor-v1"
SECRET_KEY_MARKERS = frozenset(
    {"api_key", "apikey", "secret", "token", "password", "authorization"}
)


@dataclass
class StatsConfig:
    time_saved_edit_factor: float = 2.5
    session_retention: int = 200
    deleted_path_sample_limit: int = 50


def _default_stats_config() -> StatsConfig:
    return StatsConfig()


def load_stats_config() -> StatsConfig:
    """Merge ``avo.config.json`` stats section with optional ``.avo/stats-config.json``."""
    cfg = _default_stats_config()
    cfg_file = config_path("avo.config.json")
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            stats = data.get("stats") or {}
            if isinstance(stats, dict):
                if "timeSavedEditFactor" in stats:
                    cfg.time_saved_edit_factor = float(stats["timeSavedEditFactor"])
                if "sessionRetention" in stats:
                    cfg.session_retention = int(stats["sessionRetention"])
                if "deletedPathSampleLimit" in stats:
                    cfg.deleted_path_sample_limit = int(stats["deletedPathSampleLimit"])
        except (OSError, ValueError, TypeError):
            pass

    override_path = avo_state.state_dir() / "stats-config.json"
    if override_path.is_file():
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
            if isinstance(override, dict):
                if "timeSavedEditFactor" in override:
                    cfg.time_saved_edit_factor = float(override["timeSavedEditFactor"])
                if "sessionRetention" in override:
                    cfg.session_retention = int(override["sessionRetention"])
                if "deletedPathSampleLimit" in override:
                    cfg.deleted_path_sample_limit = int(override["deletedPathSampleLimit"])
        except (OSError, ValueError, TypeError):
            pass

    return cfg


def estimate_time_saved(source_duration_seconds: float | None, factor: float) -> int | None:
    """Return estimated minutes saved using duration-factor-v1 model."""
    if source_duration_seconds is None or source_duration_seconds <= 0:
        return None
    minutes = source_duration_seconds * factor / 60.0
    return int(round(minutes))


def _reject_secrets(payload: dict[str, Any]) -> None:
    lowered_keys = {str(k).lower() for k in payload}
    if lowered_keys & SECRET_KEY_MARKERS:
        raise ValueError("session payload contains disallowed secret-like keys")


def _default_totals() -> dict[str, int]:
    return {
        "videosCompleted": 0,
        "bytesFreed": 0,
        "preservedBytes": 0,
        "estimatedMinutesSaved": 0,
    }


def _session_contribution(session: dict[str, Any]) -> dict[str, int]:
    bytes_block = session.get("bytes") or {}
    est = session.get("estimatedMinutesSaved")
    return {
        "videosCompleted": 1,
        "bytesFreed": int(bytes_block.get("freed", 0)),
        "preservedBytes": int(bytes_block.get("preserved", 0)),
        "estimatedMinutesSaved": int(est) if est is not None else 0,
    }


def _subtract_totals(totals: dict[str, int], contribution: dict[str, int]) -> None:
    totals["videosCompleted"] = max(0, totals["videosCompleted"] - contribution["videosCompleted"])
    totals["bytesFreed"] = max(0, totals["bytesFreed"] - contribution["bytesFreed"])
    totals["preservedBytes"] = max(0, totals["preservedBytes"] - contribution["preservedBytes"])
    totals["estimatedMinutesSaved"] = max(
        0, totals["estimatedMinutesSaved"] - contribution["estimatedMinutesSaved"]
    )


def _add_totals(totals: dict[str, int], contribution: dict[str, int]) -> None:
    totals["videosCompleted"] += contribution["videosCompleted"]
    totals["bytesFreed"] += contribution["bytesFreed"]
    totals["preservedBytes"] += contribution["preservedBytes"]
    totals["estimatedMinutesSaved"] += contribution["estimatedMinutesSaved"]


def _rotate_sessions(sessions: list[dict[str, Any]], retention: int) -> list[dict[str, Any]]:
    if len(sessions) <= retention:
        return sessions
    sorted_sessions = sorted(
        sessions,
        key=lambda s: str(s.get("completedAt") or s.get("startedAt") or ""),
    )
    return sorted_sessions[-retention:]


def record_session(session_payload: dict[str, Any]) -> dict[str, Any]:
    """Upsert session by id and update cumulative totals (idempotent)."""
    _reject_secrets(session_payload)
    session_id = str(session_payload["id"])
    cfg = load_stats_config()

    state = avo_state.load_state()
    stats = state.setdefault("stats", {})
    sessions: list[dict[str, Any]] = list(stats.get("sessions") or [])
    totals = dict(stats.get("totals") or _default_totals())
    for key in _default_totals():
        totals.setdefault(key, 0)

    existing_idx = next((i for i, s in enumerate(sessions) if s.get("id") == session_id), None)
    if existing_idx is not None:
        old = sessions[existing_idx]
        _subtract_totals(totals, _session_contribution(old))
        sessions[existing_idx] = session_payload
    else:
        sessions.append(session_payload)

    _add_totals(totals, _session_contribution(session_payload))
    stats["sessions"] = _rotate_sessions(sessions, cfg.session_retention)
    stats["totals"] = totals
    state["stats"] = stats
    avo_state.save_state_atomic(state)
    return session_payload


def _parse_date_prefix(iso: str | None) -> str:
    if not iso:
        return "unknown date"
    return iso[:10] if len(iso) >= 10 else iso


def _top_provider(sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sessions:
        return None
    counts = Counter(str(s.get("provider") or "unknown") for s in sessions)
    slug, count = counts.most_common(1)[0]
    return {"slug": slug, "count": count}


def _avg_freed(totals: dict[str, int]) -> float:
    completed = int(totals.get("videosCompleted", 0))
    if completed <= 0:
        return 0.0
    return int(totals.get("bytesFreed", 0)) / completed


def compute_display_metrics(
    state: dict[str, Any] | None = None,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Build structured metrics for human or JSON display."""
    state = state or avo_state.load_state()
    cfg = load_stats_config()
    stats = state.get("stats") or {}
    totals = dict(stats.get("totals") or _default_totals())
    sessions: list[dict[str, Any]] = list(stats.get("sessions") or [])

    last_session = None
    if sessions:
        last_session = max(
            sessions,
            key=lambda s: str(s.get("completedAt") or s.get("startedAt") or ""),
        )

    display: dict[str, Any] = {
        "totals": totals,
        "sessionCount": len(sessions),
        "lastSession": None,
        "topProvider": _top_provider(sessions),
        "avgFreedBytes": _avg_freed(totals),
        "estimationModel": ESTIMATION_MODEL,
        "timeSavedEditFactor": cfg.time_saved_edit_factor,
    }

    if last_session:
        display["lastSession"] = {
            "id": last_session.get("id"),
            "title": last_session.get("title") or last_session.get("masterBasename"),
            "completedAt": last_session.get("completedAt"),
            "provider": last_session.get("provider"),
        }

    if verbose:
        cut_ratios: list[float] = []
        phase_counts: list[int] = []
        gate_counts: list[int] = []
        for session in sessions:
            src = session.get("sourceDurationSeconds")
            master = session.get("masterDurationSeconds")
            if src and master and src > 0:
                cut_ratios.append(float(master) / float(src))
            phases = session.get("phases")
            if isinstance(phases, list):
                phase_counts.append(len(phases))
            gates = session.get("approvalGates")
            if isinstance(gates, list):
                gate_counts.append(len(gates))

        display["tierB"] = {
            "avgCutRatio": round(sum(cut_ratios) / len(cut_ratios), 3) if cut_ratios else None,
            "avgPhasesPerVideo": round(sum(phase_counts) / len(phase_counts), 1)
            if phase_counts
            else None,
            "avgApprovalGates": round(sum(gate_counts) / len(gate_counts), 1)
            if gate_counts
            else None,
        }
        display["tierC"] = {
            "estimatedMinutesSaved": totals.get("estimatedMinutesSaved", 0),
            "estimationModel": ESTIMATION_MODEL,
            "timeSavedEditFactor": cfg.time_saved_edit_factor,
            "disclosure": (
                f"estimated using {ESTIMATION_MODEL}: "
                f"sourceDuration × {cfg.time_saved_edit_factor} / 60"
            ),
        }

    return display


def format_human(display: dict[str, Any], *, verbose: bool = False) -> str:
    """Format Tier A (and optional B/C) human-readable stats."""
    totals = display.get("totals") or _default_totals()
    completed = int(totals.get("videosCompleted", 0))

    if completed == 0:
        return (
            "AVO stats (local only — see SECURITY.md#privacy--telemetry)\n\n"
            "No completed videos recorded yet.\n"
            "Run a full pipeline through cleanup to record your first session.\n"
        )

    lines = [
        "AVO stats (local only — see SECURITY.md#privacy--telemetry)",
        "",
        f"Videos completed:     {completed}",
        f"Disk freed:           {human_bytes(totals.get('bytesFreed', 0))}",
        f"Preserved library:    {human_bytes(totals.get('preservedBytes', 0))}",
    ]

    last = display.get("lastSession") or {}
    last_title = last.get("title") or "Untitled"
    last_date = _parse_date_prefix(last.get("completedAt"))
    lines.append(f"Last video:           {last_title} ({last_date})")

    top = display.get("topProvider")
    if top:
        lines.append(f"Top provider:         {top['slug']} ({top['count']} videos)")

    avg_freed = display.get("avgFreedBytes", 0)
    lines.append(f"Avg freed / video:    {human_bytes(avg_freed)}")

    est_minutes = int(totals.get("estimatedMinutesSaved", 0))
    factor = display.get("timeSavedEditFactor", 2.5)
    if est_minutes > 0:
        hours = est_minutes / 60.0
        if hours >= 1:
            time_label = f"~{hours:.0f}h"
        else:
            time_label = f"~{est_minutes}m"
        lines.append(
            f"Time saved (est.):    {time_label} (estimated, {factor}× source duration)"
        )
    else:
        lines.append("Time saved (est.):    n/a (source duration unknown)")

    if verbose:
        tier_b = display.get("tierB") or {}
        lines.append("")
        lines.append("Tier B (verbose):")
        if tier_b.get("avgCutRatio") is not None:
            lines.append(f"  Avg cut ratio:        {tier_b['avgCutRatio']:.2f}")
        if tier_b.get("avgPhasesPerVideo") is not None:
            lines.append(f"  Avg phases / video:   {tier_b['avgPhasesPerVideo']}")
        if tier_b.get("avgApprovalGates") is not None:
            lines.append(f"  Avg approval gates:   {tier_b['avgApprovalGates']}")

        tier_c = display.get("tierC") or {}
        lines.append("")
        lines.append("Tier C (estimation model):")
        lines.append(f"  Model:                {tier_c.get('estimationModel', ESTIMATION_MODEL)}")
        lines.append(f"  Edit factor:          {tier_c.get('timeSavedEditFactor', factor)}")
        if tier_c.get("disclosure"):
            lines.append(f"  {tier_c['disclosure']}")

    return "\n".join(lines) + "\n"


def format_json(display: dict[str, Any]) -> dict[str, Any]:
    """Trim display payload for ``--json`` stdout."""
    payload = {
        "totals": display.get("totals"),
        "lastSession": display.get("lastSession"),
        "topProvider": display.get("topProvider"),
        "estimationModel": display.get("estimationModel"),
        "timeSavedEditFactor": display.get("timeSavedEditFactor"),
    }
    if display.get("tierB"):
        payload["tierB"] = display["tierB"]
    if display.get("tierC"):
        payload["tierC"] = display["tierC"]
    return payload


def _probe_source_duration(raw_dir: Path, master_basename: str) -> float | None:
    if media_duration is None or resolve_preserved_set is None:
        return None
    preserved = resolve_preserved_set(raw_dir, master_basename)
    for path in preserved.raw_sources:
        duration = media_duration(path)
        if duration is not None:
            return duration
    return None


def _probe_master_duration(raw_dir: Path, master_basename: str) -> float | None:
    if media_duration is None:
        return None
    masters_dir = raw_dir / "edit" / "masters"
    if not masters_dir.is_dir():
        return None
    for path in sorted(masters_dir.glob(f"{master_basename}.*")):
        if path.is_file():
            return media_duration(path)
    return None


def session_from_wrap(wrap: dict[str, Any], *, wrap_path: Path | None = None) -> dict[str, Any]:
    """Convert final wrap JSON into a session record payload."""
    cfg = load_stats_config()
    raw_dir = Path(str(wrap.get("rawDir") or "")).expanduser()
    if not raw_dir.is_absolute() and wrap_path is not None:
        raw_dir = wrap_path.parent.resolve()

    master_basename = str(wrap.get("masterBasename", ""))
    space = wrap.get("space") or {}
    files = wrap.get("files") or {}

    source_duration = _probe_source_duration(raw_dir, master_basename)
    master_duration = _probe_master_duration(raw_dir, master_basename)
    est_minutes = estimate_time_saved(source_duration, cfg.time_saved_edit_factor)

    deleted_count = int(files.get("deletedCount", len(files.get("deletedOnCleanup") or [])))
    preserved_count = len(files.get("preserved") or [])
    deleted_sample = list(files.get("deletedSample") or [])

    wrap_file = wrap_path or (raw_dir / "avo.wrap.json")
    path_status = "ok" if wrap_file.is_file() else "missing"

    session: dict[str, Any] = {
        "id": str(wrap["sessionId"]),
        "provider": str(wrap.get("provider", "unknown")),
        "rawDir": str(raw_dir.resolve()),
        "title": str(wrap.get("title") or ""),
        "masterBasename": master_basename,
        "completedAt": str(wrap.get("generatedAt") or avo_state.now_iso()),
        "bytes": {
            "preCleanupProject": int(space.get("preCleanupProjectBytes", 0)),
            "freed": int(space.get("freedBytes") or 0),
            "preserved": int(space.get("preservedBytes", 0)),
        },
        "files": {
            "deletedCount": deleted_count,
            "preservedCount": preserved_count,
            "deletedSample": deleted_sample[: cfg.deleted_path_sample_limit],
        },
        "sourceDurationSeconds": source_duration,
        "masterDurationSeconds": master_duration,
        "estimatedMinutesSaved": est_minutes,
        "estimationModel": ESTIMATION_MODEL,
        "wrapPath": str(wrap_file.resolve()),
        "pathStatus": path_status,
    }
    return session


def _cmd_show(args: argparse.Namespace) -> int:
    display = compute_display_metrics(verbose=args.verbose)
    if args.json:
        payload = format_json(display)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print("AVO_JSON " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        sys.stdout.write(format_human(display, verbose=args.verbose))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    if args.stdin:
        wrap = json.load(sys.stdin)
    elif args.wrap_json:
        wrap_path = Path(args.wrap_json)
        wrap = json.loads(wrap_path.read_text(encoding="utf-8"))
    else:
        print("error: provide --wrap-json or --stdin", file=sys.stderr)
        return 1

    if wrap.get("status") != "final":
        print("error: wrap JSON must have status 'final'", file=sys.stderr)
        return 1

    wrap_path = Path(args.wrap_json) if args.wrap_json else None
    try:
        session_payload = session_from_wrap(wrap, wrap_path=wrap_path)
        record_session(session_payload)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps(session_payload, indent=2, ensure_ascii=False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="Display aggregate local stats.")
    p_show.add_argument("--json", action="store_true")
    p_show.add_argument("--verbose", action="store_true", help="Include Tier B/C metrics.")
    p_show.set_defaults(func=_cmd_show)

    p_record = sub.add_parser("record", help="Record session from final wrap JSON.")
    p_record.add_argument("--wrap-json", type=Path, default=None)
    p_record.add_argument("--stdin", action="store_true")
    p_record.set_defaults(func=_cmd_record)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
