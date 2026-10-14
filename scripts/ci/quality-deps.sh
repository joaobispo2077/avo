#!/usr/bin/env bash
# Audit the supported MCP runtime too; Python advisories and npm criticals block.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
uv run --frozen --extra dev --extra mcp python scripts/ci/check_npm_audit.py --all
