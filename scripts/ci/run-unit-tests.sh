#!/usr/bin/env bash
# Canonical unit test entry for local dev and CI. Requires: pip install -e ".[dev]"
# Default: AVO core only (excludes tests/projects — footage-project specs).
# Run all tests including projects: pytest
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ $# -eq 0 ]]; then
  # Ignore tests/projects so pytest never imports footage-project modules
  # (specs/ is gitignored; some project tests read spec files at import time).
  exec pytest --ignore=tests/projects -m "not project" "$@"
else
  exec pytest "$@"
fi
