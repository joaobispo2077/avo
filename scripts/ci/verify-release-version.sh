#!/usr/bin/env bash
# Verify git tag vX.Y.Z matches package.json, pyproject.toml, and CHANGELOG.md.
# Usage: verify-release-version.sh [v0.1.0]   (defaults to GITHUB_REF_NAME)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

RAW_TAG="${1:-${GITHUB_REF_NAME:-}}"
RAW_TAG="${RAW_TAG#refs/tags/}"
if [[ -z "$RAW_TAG" ]]; then
  echo "error: no tag provided (arg or GITHUB_REF_NAME)" >&2
  exit 1
fi
if [[ "$RAW_TAG" != v* ]]; then
  echo "error: tag must start with v (got: $RAW_TAG)" >&2
  exit 1
fi
VERSION="${RAW_TAG#v}"

python - "$VERSION" "$ROOT" <<'PY'
import json
import re
import sys
from pathlib import Path

version = sys.argv[1]
root = Path(sys.argv[2])

pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
if not match:
    print("error: could not parse version from pyproject.toml", file=sys.stderr)
    sys.exit(1)
py_ver = match.group(1)

changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
heading = f"## [{version}]"
if heading not in changelog:
    print(f"error: CHANGELOG.md missing section {heading}", file=sys.stderr)
    sys.exit(1)

errors = []
if pkg != version:
    errors.append(f"package.json version {pkg!r} != tag {version!r}")
if py_ver != version:
    errors.append(f"pyproject.toml version {py_ver!r} != tag {version!r}")

if errors:
    for msg in errors:
        print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

print(f"OK: release version {version} aligned across tag, package.json, pyproject.toml, CHANGELOG.md")
PY
