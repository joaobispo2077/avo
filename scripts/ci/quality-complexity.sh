#!/usr/bin/env bash
# Complexity gate: xenon max-absolute B on src/avo (task-010 / FR-5).
# Known debt is tracked in complexity-allowlist.json with reasons + ceilings.
# Ruff C901 (max-complexity 31) is enforced in quality:lint / quality-lint.sh.
# Fail-immediately — no soft/warn mode. No separate quality.yml (spec v1.4).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

exec python scripts/ci/check_complexity.py
