#!/usr/bin/env bash
# Format check: Ruff format --check + Prettier --check.
# Requires: `uv sync --frozen --extra dev` + npm ci (CI quality/unit path).
# Fail-immediately (task-008). Local: npm run quality:format
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:format (ruff format --check)"
ruff format --check src/avo tests helpers

echo "==> quality:format (prettier --check)"
npx --no-install prettier --check .

echo "quality:format passed."
