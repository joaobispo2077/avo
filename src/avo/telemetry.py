"""AVO telemetry & progress reporting.

At each phase boundary, report:
  - free disk space on the editing volume,
  - bytes the step created,
  - cumulative project footprint,
  - phase N-of-total + percent,
  - a rough ETA from step history.

Emits both a human line and a machine-readable JSON line (agent-consumable), and
persists rolling stats to `.avo/state.json`. The post-render learndown reports
**space used vs freed** plus the preserved-set size.

No wall-clock timing is used inside deterministic render paths; ETA lives at the
orchestration layer (this module), based on elapsed step history.

Cross-platform: pathlib + shutil, no hardcoded separators.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from avo import avo_state


def human_bytes(num: float) -> str:
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}" if unit != "B" else f"{int(num)}B"
        num /= 1024.0
    return f"{num:.1f}EB"


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def dir_size(path: Path) -> int:
    path = Path(path)
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def disk_free(path: Path) -> int:
    path = Path(path)
    probe = path if path.exists() else path.anchor or Path.cwd()
    try:
        return shutil.disk_usage(str(probe)).free
    except OSError:
        return -1


class Telemetry:
    """Phase-boundary reporter. One instance per project run."""

    def __init__(self, volume: Path | None = None, total_phases: int | None = None):
        self.volume = Path(volume) if volume else Path.cwd()
        self.total_phases = total_phases
        self._start = time.monotonic()
        self._phase_count = 0

    def _eta_seconds(self, index: int | None, total: int | None) -> float | None:
        if not index or not total or index <= 0 or index >= total:
            return None
        elapsed = time.monotonic() - self._start
        per_phase = elapsed / index
        return per_phase * (total - index)

    def _append_session_phase(self, session_id: str, record: dict[str, Any]) -> None:
        """Append phase line to ``.avo/sessions/<id>/phases.jsonl`` (local-only)."""
        phase_path = avo_state.sessions_dir() / session_id / "phases.jsonl"
        phase_path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "phase": record.get("phase"),
            "ts": record.get("ts"),
            "createdBytes": record.get("createdBytes"),
            "index": record.get("index"),
        }
        with phase_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def report(
        self,
        phase: str,
        *,
        created_bytes: int = 0,
        note: str = "",
        index: int | None = None,
        total: int | None = None,
        volume: Path | None = None,
        active_models: dict[str, str] | None = None,
        session_id: str | None = None,
        video_key: str | None = None,
        video_id: str | None = None,
        project: dict[str, Any] | None = None,
        emit: bool = True,
    ) -> dict[str, Any]:
        self._phase_count += 1
        idx = index if index is not None else self._phase_count
        tot = total if total is not None else self.total_phases
        vol = Path(volume) if volume else self.volume

        free = disk_free(vol)

        state = avo_state.load_state()
        stats = state.get("stats") or {}
        cumulative = int(stats.get("cumulativeBytes", 0)) + int(created_bytes)
        phases = stats.get("phases") or []
        record = {
            "phase": phase,
            "index": idx,
            "total": tot,
            "createdBytes": int(created_bytes),
            "cumulativeBytes": cumulative,
            "diskFreeBytes": free,
            "note": note,
            "ts": avo_state.now_iso(),
        }
        phases.append({k: record[k] for k in ("phase", "index", "createdBytes", "ts")})
        stats["phases"] = phases[-200:]
        stats["cumulativeBytes"] = cumulative
        state["stats"] = stats
        avo_state.save_state(state)

        eta = self._eta_seconds(idx, tot)
        percent = (idx / tot * 100.0) if (idx and tot) else None
        record["percent"] = round(percent, 1) if percent is not None else None
        record["etaSeconds"] = round(eta, 1) if eta is not None else None

        if active_models is None:
            try:
                from avo.models import resolve_active_models

                active_models = resolve_active_models(project=project, video_key=video_key)
            except Exception:
                active_models = {}
        if active_models:
            record["activeModels"] = active_models
        if video_key:
            record["videoKey"] = video_key
        if video_id:
            record["videoId"] = video_id

        if session_id:
            self._append_session_phase(session_id, record)

        if emit:
            phase_label = f"[{idx}/{tot}]" if tot else f"[{idx}]"
            pct = f" {percent:.0f}%" if percent is not None else ""
            models_note = ""
            if active_models:
                models_note = " | models " + ", ".join(f"{k}={v}" for k, v in active_models.items())
            line = (
                f"{phase_label}{pct} {phase} | "
                f"+{human_bytes(created_bytes)} step | "
                f"{human_bytes(cumulative)} total | "
                f"{human_bytes(free)} free | "
                f"ETA {human_duration(eta)}"
                f"{models_note}"
            )
            if note:
                line += f" | {note}"
            print(line)
            print("AVO_JSON " + json.dumps(record, ensure_ascii=False), file=sys.stderr)

        return record

    def learndown(
        self,
        *,
        used_bytes: int,
        freed_bytes: int,
        preserved_bytes: int | None = None,
        note: str = "",
        emit: bool = True,
    ) -> dict[str, Any]:
        net = int(used_bytes) - int(freed_bytes)
        record = {
            "event": "learndown",
            "usedBytes": int(used_bytes),
            "freedBytes": int(freed_bytes),
            "netBytes": net,
            "preservedBytes": int(preserved_bytes) if preserved_bytes is not None else None,
            "ts": avo_state.now_iso(),
        }

        state = avo_state.load_state()
        stats = state.get("stats") or {}
        stats["lastLearndown"] = record
        state["stats"] = stats
        avo_state.save_state(state)

        if emit:
            preserved = (
                f" | preserved {human_bytes(preserved_bytes)}"
                if preserved_bytes is not None
                else ""
            )
            sign = "-" if net >= 0 else "+"
            print(
                f"learndown | used {human_bytes(used_bytes)} | "
                f"freed {human_bytes(freed_bytes)} | "
                f"net {sign}{human_bytes(abs(net))}{preserved}"
                + (f" | {note}" if note else "")
            )
            print("AVO_JSON " + json.dumps(record, ensure_ascii=False), file=sys.stderr)

        return record

    def cleanup(
        self,
        *,
        freed_bytes: int,
        preserved_bytes: int | None = None,
        note: str = "",
        emit: bool = True,
    ) -> dict[str, Any]:
        record = {
            "event": "cleanup",
            "freedBytes": int(freed_bytes),
            "preservedBytes": int(preserved_bytes) if preserved_bytes is not None else None,
            "ts": avo_state.now_iso(),
        }

        state = avo_state.load_state()
        stats = state.get("stats") or {}
        stats["lastCleanup"] = record
        state["stats"] = stats
        avo_state.save_state(state)

        if emit:
            preserved = (
                f" | preserved {human_bytes(preserved_bytes)}"
                if preserved_bytes is not None
                else ""
            )
            print(
                f"cleanup | freed {human_bytes(freed_bytes)}{preserved}"
                + (f" | {note}" if note else "")
            )
            print("AVO_JSON " + json.dumps(record, ensure_ascii=False), file=sys.stderr)

        return record


# ---- module-level convenience ----------------------------------------------

def report(phase: str, **kwargs: Any) -> dict[str, Any]:
    return Telemetry().report(phase, **kwargs)


def learndown(**kwargs: Any) -> dict[str, Any]:
    return Telemetry().learndown(**kwargs)


def cleanup(**kwargs: Any) -> dict[str, Any]:
    return Telemetry().cleanup(**kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AVO telemetry & progress reporting.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rep = sub.add_parser("report", help="Report a phase boundary.")
    p_rep.add_argument("--phase", required=True)
    p_rep.add_argument("--created-bytes", type=int, default=0)
    p_rep.add_argument("--created-path", default="",
                       help="Measure created bytes as the size of this path (overrides --created-bytes).")
    p_rep.add_argument("--index", type=int, default=None)
    p_rep.add_argument("--total", type=int, default=None)
    p_rep.add_argument("--volume", default="")
    p_rep.add_argument("--note", default="")
    p_rep.add_argument("--session-id", default="", help="Optional session id for phases.jsonl log.")

    p_ld = sub.add_parser("learndown", help="Report post-render space used vs freed.")
    p_ld.add_argument("--used", type=int, default=0)
    p_ld.add_argument("--freed", type=int, default=0)
    p_ld.add_argument("--preserved", type=int, default=None)
    p_ld.add_argument("--preserved-path", default="",
                      help="Measure preserved bytes as the size of this path.")
    p_ld.add_argument("--note", default="")

    p_cl = sub.add_parser("cleanup", help="Report post-cleanup freed/preserved bytes.")
    p_cl.add_argument("--freed", type=int, default=0)
    p_cl.add_argument("--preserved", type=int, default=None)
    p_cl.add_argument("--preserved-path", default="",
                      help="Measure preserved bytes as the size of this path.")
    p_cl.add_argument("--note", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tel = Telemetry(volume=Path(args.volume) if getattr(args, "volume", "") else None)

    if args.cmd == "report":
        created = args.created_bytes
        if args.created_path:
            created = dir_size(Path(args.created_path))
        tel.report(
            args.phase,
            created_bytes=created,
            note=args.note,
            index=args.index,
            total=args.total,
            volume=Path(args.volume) if args.volume else None,
            session_id=args.session_id or None,
        )
        return 0

    if args.cmd == "learndown":
        preserved = args.preserved
        if args.preserved_path:
            preserved = dir_size(Path(args.preserved_path))
        tel.learndown(
            used_bytes=args.used,
            freed_bytes=args.freed,
            preserved_bytes=preserved,
            note=args.note,
        )
        return 0

    if args.cmd == "cleanup":
        preserved = args.preserved
        if args.preserved_path:
            preserved = dir_size(Path(args.preserved_path))
        tel.cleanup(
            freed_bytes=args.freed,
            preserved_bytes=preserved,
            note=args.note,
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
