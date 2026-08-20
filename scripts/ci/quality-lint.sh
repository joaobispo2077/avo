#!/usr/bin/env bash
# Static lint: Ruff (Python) + ESLint (JS/TS).
# Requires: `uv sync --frozen --extra dev` + npm ci (CI quality/unit path).
# Fail-immediately (task-008). Local: npm run quality:lint
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:lint (ruff check)"
ruff check src/avo tests helpers

echo "==> quality:lint (eslint)"
npx --no-install eslint .

echo "quality:lint passed."
