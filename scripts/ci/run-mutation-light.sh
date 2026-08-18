#!/usr/bin/env bash
# Light/PR mutation (task-027 / FR-7 / ci-quality-hardening). May reuse mutants/ cache.
# Ubuntu-only. Patches [tool.mutmut] from mutation-config.json light profile.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export AVO_MUTATION_PROFILE="${AVO_MUTATION_PROFILE:-light}"

restore_mutmut_profile() {
  uv run --frozen --extra dev python scripts/ci/patch_mutmut_profile.py restore || true
}
trap restore_mutmut_profile EXIT

echo "==> mutation light (profile=${AVO_MUTATION_PROFILE}; cache allowed; 20m job SLA)"
uv run --frozen --extra dev python scripts/ci/patch_mutmut_profile.py apply "${AVO_MUTATION_PROFILE}"
uv run --frozen --extra dev mutmut run
uv run --frozen --extra dev python scripts/ci/check_mutation.py

mkdir -p reports/mutation
if [ -f mutants/mutmut-cicd-stats.json ]; then
  cp mutants/mutmut-cicd-stats.json reports/mutation/mutmut-cicd-stats-light.json
fi
echo "mutation light finished."
