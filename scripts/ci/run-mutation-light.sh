#!/usr/bin/env bash
# Light/PR mutation (task-027 / FR-7). May reuse mutants/ cache. Ubuntu-only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export AVO_MUTATION_PROFILE="${AVO_MUTATION_PROFILE:-light}"

echo "==> mutation light (profile=${AVO_MUTATION_PROFILE}; cache allowed)"
uv run --frozen --extra dev mutmut run
uv run --frozen --extra dev python scripts/ci/check_mutation.py

mkdir -p reports/mutation
if [ -f mutants/mutmut-cicd-stats.json ]; then
  cp mutants/mutmut-cicd-stats.json reports/mutation/mutmut-cicd-stats-light.json
fi
echo "mutation light finished."
