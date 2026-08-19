#!/usr/bin/env bash
# Full mutation backstop (task-018/019 / ci-quality-hardening). Ubuntu CI — mutmut
# is not native Windows. Does not use mutants/ cache as source of truth.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export AVO_MUTATION_PROFILE="${AVO_MUTATION_PROFILE:-full}"

restore_mutmut_profile() {
  uv run --frozen --extra dev python scripts/ci/patch_mutmut_profile.py restore || true
}
trap restore_mutmut_profile EXIT

echo "==> quality:mutation (profile=${AVO_MUTATION_PROFILE}, no incremental truth, 20m job SLA)"
rm -rf mutants
uv run --frozen --extra dev python scripts/ci/patch_mutmut_profile.py apply "${AVO_MUTATION_PROFILE}"
uv run --frozen --extra dev mutmut run
uv run --frozen --extra dev mutmut export-cicd-stats

mkdir -p reports/mutation
if [ -f mutants/mutmut-cicd-stats.json ]; then
  cp mutants/mutmut-cicd-stats.json reports/mutation/mutmut-cicd-stats.json
fi
uv run --frozen --extra dev python scripts/ci/check_mutation.py
echo "quality:mutation finished."
