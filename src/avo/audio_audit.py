"""Unified read-only audio audit: loudness, noise, and EQ suggestions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from avo import audio_analysis
from avo import audio_eq
from avo import audio_gain
from avo import audio_restoration
from avo import loudness_profiles

STRICT_LU_TOLERANCE = 2.0


def _load_context(
    project_path: Path | None,
    edl_path: Path | None,
) -> tuple[dict, dict, dict]:
    edl: dict = {}
    if edl_path and edl_path.exists():
        edl = json.loads(edl_path.read_text(encoding="utf-8"))

    project: dict = {}
    provider: dict = {}
    if project_path and project_path.exists():
        project = loudness_profiles.load_project_json(project_path)
        slug = str(project.get("provider") or "").strip()
        if slug:
            from avo.init_project import load_provider

            try:
                provider = load_provider(slug)
            except FileNotFoundError:
                provider = {}
    elif edl_path:
        project, provider = loudness_profiles.load_context_for_edit_dir(edl_path.parent)
    return edl, project, provider


def build_audit_report(
    media: Path,
    *,
    transcript: Path | None = None,
    edl: dict | None = None,
    project: dict | None = None,
    provider: dict | None = None,
    preset_override: str | None = None,
) -> dict[str, Any]:
    edl = edl or {}
    project = project or {}
    provider = provider or {}

    profile = loudness_profiles.resolve_loudness_profile(
        edl,
        project,
        provider,
        preset_override=preset_override,
    )

    loudness_section: dict[str, Any] | None = None
    warnings: list[str] = []

    measurement = loudness_profiles.measure_loudness(media, profile)
    if measurement is None:
        warnings.append("Loudness measurement failed — ffmpeg ebur128 unavailable or silent input")
    else:
        loudness_section = loudness_profiles.compare_measurement(measurement, profile)
        integrated = loudness_section.get("integrated_lufs")
        target = loudness_section.get("target_integrated_lufs")
        if integrated is not None and target is not None:
            delta = abs(float(integrated) - float(target))
            if delta >= STRICT_LU_TOLERANCE:
                warnings.append(
                    f"Integrated loudness {integrated:.1f} LUFS is {delta:.1f} LU from target {target:.1f} LUFS"
                )

    nr_warning = loudness_profiles.nr_loudness_warning(edl, profile)
    if nr_warning:
        warnings.append(nr_warning)

    nr_suggestions = audio_analysis.suggest_noise_reduction(media, transcript)
    eq_suggestions = audio_eq.suggest_eq(media)
    gain_suggestions = audio_gain.suggest_gain(media, transcript)

    return {
        "media": str(media.resolve()),
        "read_only": True,
        "loudness": loudness_section,
        "loudness_profile": profile.to_dict(),
        "noise_reduction": {
            "suggestions": [s.to_dict() for s in nr_suggestions],
            "default_strength_pct": audio_restoration.ENGINE_DEFAULT_PCT,
        },
        "eq": {
            "suggestions": [s.to_dict() for s in eq_suggestions],
        },
        "gain": {
            "suggestions": [s.to_dict() for s in gain_suggestions],
            "default_boost_pct": audio_gain.ENGINE_DEFAULT_BOOST_PCT,
        },
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path, help="Video or audio file to audit")
    parser.add_argument("--project", type=Path, help="avo.project.json for loudness profile resolution")
    parser.add_argument("--edl", type=Path, help="edl.json for loudness and segment overrides")
    parser.add_argument("--transcript", type=Path, help="Word-timed transcript JSON")
    parser.add_argument("--out-dir", type=Path, help="Output directory (default: cwd)")
    parser.add_argument("--loudness-preset", dest="loudness_preset", help="Override loudness preset id")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when integrated loudness is outside target ±2 LU",
    )
    args = parser.parse_args(argv)

    if not args.media.exists():
        print(f"error: media not found: {args.media}", file=sys.stderr)
        return 1

    edl, project, provider = _load_context(args.project, args.edl)

    try:
        report = build_audit_report(
            args.media,
            transcript=args.transcript,
            edl=edl,
            project=project,
            provider=provider,
            preset_override=args.loudness_preset,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_dir = args.out_dir or Path(".")
    json_path = out_dir / "audio-audit.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if args.strict and report.get("loudness"):
        loudness = report["loudness"]
        integrated = loudness.get("integrated_lufs")
        target = loudness.get("target_integrated_lufs")
        if integrated is not None and target is not None:
            if abs(float(integrated) - float(target)) >= STRICT_LU_TOLERANCE:
                return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
