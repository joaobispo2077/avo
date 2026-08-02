"""Map between camera source time and EDL output (B-time).

All cut and overlay planning must anchor on **source time** on the main
master file, then derive ``start_in_output`` after ranges are final.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Range:
    source: str
    start: float
    end: float
    story_section_id: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_ranges(edl: dict) -> list[Range]:
    ranges: list[Range] = []
    for item in edl.get("ranges") or []:
        ranges.append(
            Range(
                source=str(item["source"]),
                start=float(item["start"]),
                end=float(item["end"]),
                story_section_id=item.get("story_section_id"),
            )
        )
    return ranges


def output_duration(ranges: list[Range]) -> float:
    return sum(item.duration for item in ranges)


def source_to_output(ranges: list[Range], source_time: float) -> float | None:
    """Return B-time for a point on the main source timeline, or None if cut."""
    offset = 0.0
    for item in ranges:
        if source_time < item.start - 1e-6:
            return None
        if source_time <= item.end + 1e-6:
            return offset + (source_time - item.start)
        offset += item.duration
    return None


def output_to_source(ranges: list[Range], output_time: float) -> float | None:
    """Return main-source time for a B-time position."""
    offset = 0.0
    for item in ranges:
        if output_time <= offset + item.duration + 1e-6:
            if output_time < offset - 1e-6:
                return None
            return item.start + (output_time - offset)
        offset += item.duration
    return None


def format_mmss(seconds: float) -> str:
    whole = max(0, int(seconds))
    millis = int(round((seconds - whole) * 1000))
    minutes, secs = divmod(whole, 60)
    if millis:
        return f"{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}"


def remap_timed_items(
    edl: dict,
    *,
    anchor_field: str = "anchor_in_source",
    start_field: str = "start_in_output",
) -> dict[str, list[dict[str, Any]]]:
    """Recompute output starts from source anchors for overlays and SFX."""
    ranges = parse_ranges(edl)
    updated: dict[str, list[dict[str, Any]]] = {}
    for key in ("overlays", "sound_effects"):
        items = edl.get(key) or []
        if not items:
            continue
        remapped: list[dict[str, Any]] = []
        for item in items:
            copy = dict(item)
            anchor = copy.get(anchor_field)
            if anchor is None:
                remapped.append(copy)
                continue
            mapped = source_to_output(ranges, float(anchor))
            if mapped is None:
                raise ValueError(
                    f"{key} {_item_label(copy)} anchor {anchor} falls inside a cut"
                )
            copy[start_field] = round(mapped, 3)
            remapped.append(copy)
        updated[key] = remapped
    return updated


def _item_label(item: dict[str, Any]) -> str:
    return str(item.get("motion_brief_id") or item.get("file") or "<item>")


def verify_timed_items(edl: dict, *, tolerance: float = 0.05) -> list[str]:
    """Return errors when start_in_output disagrees with anchor_in_source."""
    ranges = parse_ranges(edl)
    errors: list[str] = []
    for key in ("overlays", "sound_effects"):
        for item in edl.get(key) or []:
            anchor = item.get("anchor_in_source")
            start = item.get("start_in_output")
            if anchor is None or start is None:
                continue
            expected = source_to_output(ranges, float(anchor))
            if expected is None:
                errors.append(
                    f"{key} {_item_label(item)} anchor {anchor} is inside a removed range"
                )
                continue
            if abs(float(start) - expected) > tolerance:
                errors.append(
                    f"{key} {_item_label(item)} start_in_output {start} != "
                    f"mapped {expected:.3f} from anchor {anchor}"
                )
    return errors


def cut_map_rows(edl: dict) -> list[dict[str, str]]:
    """Build human-readable cut rows from blocked ranges + range gaps."""
    ranges = parse_ranges(edl)
    rows: list[dict[str, str]] = []
    for item in edl.get("blocked_source_ranges") or []:
        cut_start = float(item["final_cut_start"])
        cut_end = float(item["final_cut_end"])
        b_start = source_to_output(ranges, cut_start)
        b_end = source_to_output(ranges, cut_end)
        rows.append(
            {
                "reason": str(item.get("reason") or "cut"),
                "source_in": f"{format_mmss(cut_start)}–{format_mmss(cut_end)}",
                "source_seconds": f"{cut_start:.2f}–{cut_end:.2f}",
                "removed_seconds": f"{cut_end - cut_start:.2f}",
                "b_time_if_kept_start": format_mmss(b_start) if b_start is not None else "cut",
                "b_time_if_kept_end": format_mmss(b_end) if b_end is not None else "cut",
                "user_note": str(item.get("user_note") or ""),
            }
        )
    return rows


def render_cut_map_markdown(edl: dict) -> str:
    duration = output_duration(parse_ranges(edl))
    lines = [
        "# Cut map (source ↔ B-time)",
        "",
        "Anchor every cut on **source time** on the main camera file. After any",
        "range change, re-run `python -m avo.edl_timeline verify <edl.json>` and",
        "refresh overlay `start_in_output` from `anchor_in_source`.",
        "",
        f"**Output duration:** {format_mmss(duration)} ({duration:.1f}s)",
        "",
        "| Reason | Source removed | Δ sec | User note |",
        "| --- | --- | --- | --- |",
    ]
    for row in cut_map_rows(edl):
        lines.append(
            f"| {row['reason']} | {row['source_in']} | {row['removed_seconds']} | {row['user_note']} |"
        )
    lines.extend(["", "## Range kept spans (main source)", ""])
    offset = 0.0
    for index, item in enumerate(parse_ranges(edl), start=1):
        lines.append(
            f"{index}. `{format_mmss(item.start)}–{format_mmss(item.end)}` "
            f"→ B `{format_mmss(offset)}–{format_mmss(offset + item.duration)}` "
            f"({item.story_section_id or 'section'})"
        )
        offset += item.duration
    return "\n".join(lines) + "\n"


def render_beat_map_markdown(edl: dict) -> str:
    ranges = parse_ranges(edl)
    duration = output_duration(ranges)
    lines = [
        "# Animation beat map (B-time)",
        "",
        "Review overlays and SFX in the player at **B-time** (output position).",
        f"Output duration: **{format_mmss(duration)}**.",
        "",
        "| B-time (out) | Source anchor | Slot | SFX |",
        "| --- | --- | --- | --- |",
    ]
    sfx_by_slot = {
        str(item.get("motion_brief_id")): item for item in edl.get("sound_effects") or []
    }
    for overlay in edl.get("overlays") or []:
        slot = str(overlay.get("motion_brief_id") or overlay.get("file"))
        start = float(overlay["start_in_output"])
        anchor = overlay.get("anchor_in_source")
        anchor_text = format_mmss(float(anchor)) if anchor is not None else "—"
        sfx = sfx_by_slot.get(slot)
        sfx_text = "—"
        if sfx:
            sfx_text = f"`{sfx.get('file')}` @ {format_mmss(float(sfx['start_in_output']))}"
        lines.append(
            f"| **{format_mmss(start)}** | {anchor_text} | {slot} | {sfx_text} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    verify_parser = sub.add_parser("verify", help="Check anchor/output consistency")
    verify_parser.add_argument("edl", type=Path)

    map_parser = sub.add_parser("map", help="Print source↔output mapping for a timestamp")
    map_parser.add_argument("edl", type=Path)
    map_parser.add_argument("time", type=float)
    map_parser.add_argument(
        "--from",
        dest="from_mode",
        choices=("source", "output"),
        default="source",
        help="Interpret TIME as source seconds (default) or output seconds",
    )

    docs_parser = sub.add_parser("write-docs", help="Write cut-map.md and beat-map.md")
    docs_parser.add_argument("edl", type=Path)
    docs_parser.add_argument("--edit-dir", type=Path, default=None)

    args = parser.parse_args()
    edl_path = args.edl.resolve()
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    ranges = parse_ranges(edl)

    if args.command == "verify":
        errors = verify_timed_items(edl)
        if errors:
            raise SystemExit("timeline verify failed:\n- " + "\n- ".join(errors))
        print(f"ok: {len(ranges)} ranges, output {output_duration(ranges):.3f}s")
        return

    if args.command == "map":
        if args.from_mode == "source":
            mapped = source_to_output(ranges, args.time)
            print(f"source {args.time:.3f}s -> output {mapped}")
        else:
            mapped = output_to_source(ranges, args.time)
            print(f"output {args.time:.3f}s -> source {mapped}")
        return

    edit_dir = (args.edit_dir or edl_path.parent).resolve()
    (edit_dir / "cut-map.md").write_text(render_cut_map_markdown(edl), encoding="utf-8")
    (edit_dir / "animations" / "beat-map.md").write_text(
        render_beat_map_markdown(edl), encoding="utf-8"
    )
    print(f"wrote {edit_dir / 'cut-map.md'}")
    print(f"wrote {edit_dir / 'animations' / 'beat-map.md'}")


if __name__ == "__main__":
    main()
