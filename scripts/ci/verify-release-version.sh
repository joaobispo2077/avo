#!/usr/bin/env bash
# Verify git tag vX.Y.Z matches package.json, pyproject.toml, and CHANGELOG.md.
# Used post semantic-release in CI and for optional manual/emergency tag checks.
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

python "$ROOT/scripts/ci/verify-release-version.py" "$VERSION"
