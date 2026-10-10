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
uv run --frozen --extra dev mutmut export-cicd-stats

# Stamp only after export. set -e skips this when clean tests fail, so a
# restored mutants/ cache cannot be labeled as this run's score.
if [ -n "${GITHUB_SHA:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
  uv run --frozen --extra dev python scripts/ci/write_mutation_pr_report.py \
    --stamp mutants/mutmut-cicd-stats.json
fi

mkdir -p reports/mutation
if [ -f mutants/mutmut-cicd-stats.json ]; then
  cp mutants/mutmut-cicd-stats.json reports/mutation/mutmut-cicd-stats-light.json
fi
uv run --frozen --extra dev python scripts/ci/check_mutation.py
echo "mutation light finished."
