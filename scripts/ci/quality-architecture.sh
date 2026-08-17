#!/usr/bin/env bash
# Architecture / import boundaries (task-016): import-linter contracts in .importlinter.
# Fail-immediately on forbidden imports. Spec v1.4: ci.yml software-quality only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:architecture (lint-imports)"
uv run --frozen --extra dev lint-imports --config .importlinter

echo "quality:architecture passed."
