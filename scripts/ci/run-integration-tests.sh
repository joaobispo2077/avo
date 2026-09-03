#!/usr/bin/env bash
# Integration pytest entry for local dev and CI (subprocess/runtime boundaries).
# Requires: `uv sync --frozen --extra dev` (CI) or `uv run --frozen --extra dev` (npm).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
exec pytest tests/integration -m "integration and not project" "$@"
