#!/usr/bin/env bash
# Coverage report + fail-under for AVO core (excludes tests/projects).
# Requires: uv sync --frozen --extra dev (CI) or equivalent locked env.
# Default floor matches [tool.coverage.report] fail_under in pyproject.toml.
# Override with COV_FAIL_UNDER=N only when deliberately ratcheting in CI experiments.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

FAIL_UNDER="${COV_FAIL_UNDER:-68}"
mkdir -p reports/quality

ARGS=(
  pytest
  --ignore=tests/projects
  --ignore=tests/integration
  -m "not project and not integration"
  --cov=avo
  --cov-report=term-missing
  --cov-report=json:reports/quality/coverage.json
  --cov-fail-under="${FAIL_UNDER}"
)

exec "${ARGS[@]}" "$@"
