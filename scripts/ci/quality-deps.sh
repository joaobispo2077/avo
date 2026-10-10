#!/usr/bin/env bash
# Shared pip-audit + critical-only npm policy; no warn-only mode.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
uv run --frozen --extra dev python scripts/ci/check_npm_audit.py --all
