#!/usr/bin/env bash
# Dead-code gate: vulture on src/avo with JSON allowlist (task-014 / FR-8).
# min_confidence 60 (see deadcode-allowlist.json). Dynamic adapters, CLI/MCP
# entrypoints, and Protocol surfaces must be allowlisted with path/name/reason.
# Fail-immediately — no soft/warn mode. No separate quality.yml (spec v1.4).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

exec uv run --frozen --extra dev python scripts/ci/check_deadcode.py
