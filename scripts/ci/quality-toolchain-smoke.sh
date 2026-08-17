#!/usr/bin/env bash
# Prove quality/mutation CLIs install and run (task-028 / FR-13).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
mkdir -p reports/toolchain-smoke

{
  echo "==> ruff"
  uv run --frozen --extra dev ruff --version
  echo "==> xenon"
  uv run --frozen --extra dev xenon --version
  echo "==> vulture"
  uv run --frozen --extra dev vulture --version
  echo "==> pip-audit"
  uv run --frozen --extra dev pip-audit --version
  echo "==> lint-imports"
  uv run --frozen --extra dev lint-imports --help >/dev/null
  echo "lint-imports help ok"
  echo "==> mutmut"
  uv run --frozen --extra dev mutmut --version
  echo "==> jscpd"
  npx --no-install jscpd --version
} | tee reports/toolchain-smoke/cli-versions.txt

echo "quality toolchain smoke passed."
