#!/usr/bin/env bash
# Canonical unit test entry for local dev and CI. Requires: pip install -e ".[dev]"
# Default: AVO core only (excludes tests/projects — footage-project specs).
# Run all tests including projects: pytest
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ $# -eq 0 ]]; then
  exec pytest -m "not project" "$@"
else
  exec pytest "$@"
fi
