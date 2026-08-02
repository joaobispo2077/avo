#!/usr/bin/env python3
"""Verify release version alignment across package.json, pyproject.toml, CHANGELOG.md."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def changelog_has_version(changelog: str, version: str) -> bool:
    escaped = re.escape(version)
    patterns = (
        rf"^## \[{escaped}\](?:\(|\s|$)",
        rf"^# {escaped}(?:\s|\(|$)",
    )
    return any(re.search(pattern, changelog, re.MULTILINE) for pattern in patterns)


def verify_release_version(version: str, root: Path) -> None:
    pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if not match:
        raise SystemExit("error: could not parse version from pyproject.toml")
    py_ver = match.group(1)

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not changelog_has_version(changelog, version):
        raise SystemExit(
            f"error: CHANGELOG.md missing section for version {version!r} "
            f"(expected ## [{version}] or # {version} (...))"
        )

    errors: list[str] = []
    if pkg != version:
        errors.append(f"package.json version {pkg!r} != tag {version!r}")
    if py_ver != version:
        errors.append(f"pyproject.toml version {py_ver!r} != tag {version!r}")
    if errors:
        for msg in errors:
            print(f"error: {msg}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"OK: release version {version} aligned across tag, "
        "package.json, pyproject.toml, CHANGELOG.md"
    )


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: verify-release-version.py <version>")
    version = args[0]
    root = Path(__file__).resolve().parents[2]
    verify_release_version(version, root)


if __name__ == "__main__":
    main()
