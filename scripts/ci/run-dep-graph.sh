#!/usr/bin/env bash
# Weekly HTML dependency table + DOT export for src/avo. Non-blocking for PRs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:dep-graph"
uv run --frozen --extra dev python scripts/ci/avo_dep_graph.py
echo "quality:dep-graph finished."
