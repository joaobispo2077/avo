#!/usr/bin/env bash
# Canonical unit test entry for local dev and CI.
# Requires: `uv sync --frozen --extra dev` (CI) or `uv run --frozen --extra dev` (npm).
# Default: AVO core unit tests only (excludes tests/projects and tests/integration).
# Run all tests including projects: pytest
# Run integration only: scripts/ci/run-integration-tests.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ $# -eq 0 ]]; then
  # Ignore tests/projects so pytest never imports footage-project modules
  # (specs/ is gitignored; some project tests read spec files at import time).
  # Ignore tests/integration so the unit lane stays fast (own CI job).
  exec pytest --ignore=tests/projects --ignore=tests/integration -m "not project and not integration" "$@"
else
  exec pytest "$@"
fi
