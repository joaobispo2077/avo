"""External voiceover EDL helpers, preflight, and validation CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from avo.validate_edl import DEFAULT_SCHEMA, EdlValidationError, load_and_validate

PROGRAM_MODE = "external_voiceover"


def is_external_voiceover_edl(edl: dict) -> bool:
    return (edl.get("audio") or {}).get("program_mode") == PROGRAM_MODE


def voiceover_source_key(edl: dict) -> str:
    return str((edl.get("audio") or {}).get("voiceover_source") or "voiceover")


def _source_path_value(source_record: object) -> str:
    if isinstance(source_record, dict):
        return str(source_record.get("path") or "")
    return str(source_record)


def resolve_edit_path(maybe_path: str, base: Path) -> Path:
    path = Path(maybe_path)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def resolve_voiceover_path(edl: dict, edit_dir: Path) -> Path:
    key = voiceover_source_key(edl)
    sources = edl.get("sources") or {}
    if key not in sources:
        raise ValueError(f"voiceover source '{key}' does not resolve in sources")
    return resolve_edit_path(_source_path_value(sources[key]), edit_dir)


def output_duration_from_edl(edl: dict) -> float:
    total = 0.0
    for item in edl.get("ranges") or []:
        try:
            total += float(item["end"]) - float(item["start"])
        except (KeyError, TypeError, ValueError):
            continue
    return total


def media_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def preflight(edl: dict, edit_dir: Path) -> list[str]:
    """Return blocking issues before a voiceover render."""
    issues: list[str] = []
    if not is_external_voiceover_edl(edl):
        return ["EDL audio.program_mode must be external_voiceover"]

    try:
        vo_path = resolve_voiceover_path(edl, edit_dir)
    except ValueError as exc:
        return [str(exc)]

    if not vo_path.exists():
        issues.append(f"voiceover file missing: {vo_path}")
        return issues

    cut_duration = output_duration_from_edl(edl)
    vo_duration = media_duration(vo_path)
    if vo_duration is not None and vo_duration + 0.05 < cut_duration:
        issues.append(
            "voiceover duration "
            f"({vo_duration:.2f}s) is shorter than cut duration ({cut_duration:.2f}s)"
        )
    return issues


def validate_voiceover_edl(edl_path: Path, schema_path: Path = DEFAULT_SCHEMA) -> dict:
    edl = load_and_validate(edl_path, schema_path=schema_path)
    if not is_external_voiceover_edl(edl):
        raise EdlValidationError("EDL is not an external_voiceover program")
    issues = preflight(edl, edl_path.parent)
    if issues:
        raise EdlValidationError("Voiceover preflight failed:\n- " + "\n- ".join(issues))
    return edl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edl", type=Path, help="Path to voiceover EDL JSON")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run schema + semantic validation and duration preflight",
    )
    args = parser.parse_args()
    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl not found: {edl_path}")

    try:
        edl = validate_voiceover_edl(edl_path, schema_path=args.schema)
    except (EdlValidationError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))

    cut_duration = output_duration_from_edl(edl)
    vo_path = resolve_voiceover_path(edl, edl_path.parent)
    print(
        f"valid voiceover EDL: {len(edl.get('ranges', []))} ranges, "
        f"cut {cut_duration:.2f}s, VO {vo_path.name}"
    )
    if args.preflight_only:
        print("preflight: ok")


if __name__ == "__main__":
    main()
