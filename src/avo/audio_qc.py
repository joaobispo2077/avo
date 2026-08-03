"""Audio delivery loudness QC for approved masters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from avo import loudness_profiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path, help="Approved master video or audio file")
    parser.add_argument("--project", type=Path, help="Path to avo.project.json")
    parser.add_argument("--edl", type=Path, help="Optional edl.json for EDL audio overrides")
    parser.add_argument("--upload-candidate", type=Path, help="Re-encoded upload file for TP re-check")
    parser.add_argument("--out", type=Path, help="Write JSON QC report to this path")
    parser.add_argument("--loudness-preset", dest="loudness_preset", help="Override preset for this run")
    args = parser.parse_args(argv)

    if not args.master.exists():
        print(f"error: master not found: {args.master}", file=sys.stderr)
        return 1

    edl: dict = {}
    if args.edl and args.edl.exists():
        edl = json.loads(args.edl.read_text(encoding="utf-8"))

    project: dict = {}
    provider: dict = {}
    if args.project and args.project.exists():
        project = loudness_profiles.load_project_json(args.project)
        provider_slug = str(project.get("provider") or "").strip()
        if provider_slug:
            from avo.init_project import load_provider

            try:
                provider = load_provider(provider_slug)
            except FileNotFoundError:
                provider = {}
    elif args.edl:
        project, provider = loudness_profiles.load_context_for_edit_dir(args.edl.parent)

    try:
        profile = loudness_profiles.resolve_loudness_profile(
            edl,
            project,
            provider,
            preset_override=args.loudness_preset,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    measurement = loudness_profiles.measure_loudness(args.master, profile)
    if measurement is None:
        print("error: loudness measurement failed", file=sys.stderr)
        return 1

    upload_measurement = None
    if args.upload_candidate:
        if not args.upload_candidate.exists():
            print(f"error: upload candidate not found: {args.upload_candidate}", file=sys.stderr)
            return 1
        upload_measurement = loudness_profiles.measure_loudness(args.upload_candidate, profile)

    report = loudness_profiles.evaluate_qc(
        measurement,
        profile,
        upload_measurement=upload_measurement,
    )
    if profile.legacy_warning:
        report["legacy_warning"] = (
            "WARN: undeclared loudness target; using default reference preset "
            f"({profile.preset_label})"
        )

    payload = {
        "master": str(args.master.resolve()),
        "profile": profile.to_dict(),
        "qc": report,
    }
    text = json.dumps(payload, indent=2)
    print(text)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")

    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
