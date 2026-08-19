#!/usr/bin/env bash
# Weekly visual import graph for src/avo (task-026 / FR-12). Non-blocking for PRs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:dep-graph"
uv run --frozen --extra dev python scripts/ci/avo_dep_graph.py
echo "quality:dep-graph finished."
