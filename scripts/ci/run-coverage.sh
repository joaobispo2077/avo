#!/usr/bin/env bash
# Coverage report + fail-under for AVO core (excludes tests/projects).
# Requires: uv sync --frozen --extra dev (CI) or equivalent locked env.
# The authoritative floor is [tool.coverage.report] fail_under in pyproject.toml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

mkdir -p reports/quality

ARGS=(
  pytest
  --ignore=tests/projects
  --ignore=tests/integration
  -m "not project and not integration"
  --cov=avo
  --cov-report=term-missing
  --cov-report=json:reports/quality/coverage.json
)

exec "${ARGS[@]}" "$@"
