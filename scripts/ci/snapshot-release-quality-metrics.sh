#!/usr/bin/env bash
# Release-cut readout. Downloads the green Software quality JSON for RELEASE_SHA
# and writes docs/quality-metrics.md. Missing JSON or a SHA mismatch exits 1.
# Does not re-run gates and does not keep going after a snapshot failure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [ -z "${RELEASE_SHA:-}" ] || [ -z "${RELEASE_VERSION:-}" ]; then
  echo "quality metrics snapshot failed: RELEASE_SHA and RELEASE_VERSION are required" >&2
  exit 1
fi
if [ -z "${GITHUB_REPOSITORY:-}" ]; then
  echo "quality metrics snapshot failed: GITHUB_REPOSITORY is required" >&2
  exit 1
fi

case "$RELEASE_VERSION" in
  */*|..*)
    echo "quality metrics snapshot failed: unsafe version ${RELEASE_VERSION}" >&2
    exit 1
    ;;
esac

CHECKOUT_SHA="$(git rev-parse HEAD)"
if [ "$CHECKOUT_SHA" != "$RELEASE_SHA" ]; then
  echo "quality metrics snapshot failed: checkout ${CHECKOUT_SHA} != tip ${RELEASE_SHA}" >&2
  exit 1
fi

RUN_ID="${QUALITY_RUN_ID:-}"
if [ -z "$RUN_ID" ]; then
  RUN_ID="$(
    gh run list \
      --repo "$GITHUB_REPOSITORY" \
      --workflow ci.yml \
      --commit "$RELEASE_SHA" \
      --status success \
      --json databaseId,headSha,conclusion \
      --jq "[.[] | select(.headSha==\"${RELEASE_SHA}\" and .conclusion==\"success\")][0].databaseId // empty"
  )"
fi
if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
  echo "quality metrics snapshot failed: no green CI run for ${RELEASE_SHA}" >&2
  exit 1
fi

ACTUAL_SHA="$(gh run view "$RUN_ID" --repo "$GITHUB_REPOSITORY" --json headSha --jq .headSha)"
if [ "$ACTUAL_SHA" != "$RELEASE_SHA" ]; then
  echo "quality metrics snapshot failed: CI run ${RUN_ID} is ${ACTUAL_SHA}, tip is ${RELEASE_SHA}" >&2
  exit 1
fi

ARTIFACT_DIR="reports/quality/ci-artifact"
rm -rf "$ARTIFACT_DIR"
mkdir -p "$ARTIFACT_DIR"
gh run download "$RUN_ID" \
  --repo "$GITHUB_REPOSITORY" \
  --name quality-metrics \
  --dir "$ARTIFACT_DIR"

METRICS="${ARTIFACT_DIR}/quality-metrics.json"
if [ ! -f "$METRICS" ]; then
  echo "quality metrics snapshot failed: quality-metrics.json missing for ${RELEASE_SHA}" >&2
  exit 1
fi

CHART_ARGS=()
CHART_SRC="reports/quality/chart-artifact"
rm -rf "$CHART_SRC"
if gh run download "$RUN_ID" \
  --repo "$GITHUB_REPOSITORY" \
  --name quality-metrics-charts \
  --dir "$CHART_SRC"; then
  CHART_ARGS=(--charts-src "$CHART_SRC" --charts-dir "docs/quality/charts/${RELEASE_VERSION}")
else
  echo "quality chart artifact absent; writing tables only"
fi

MUTATION_ARGS=()
MUTATION_DIR="reports/mutation/ci-artifact"
rm -rf "$MUTATION_DIR"
if gh run download "$RUN_ID" \
  --repo "$GITHUB_REPOSITORY" \
  --name mutation-reports-light \
  --dir "$MUTATION_DIR"; then
  if [ -f "${MUTATION_DIR}/mutation-metrics.json" ]; then
    MUTATION_ARGS=(--mutation "${MUTATION_DIR}/mutation-metrics.json")
  else
    echo "mutation metrics JSON absent; snapshot records a dash"
  fi
else
  echo "mutation artifact absent; snapshot records a dash"
fi

if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "quality metrics snapshot failed: python is not installed" >&2
  exit 1
fi

"$PY" scripts/ci/write_quality_metrics_snapshot.py \
  --metrics "$METRICS" \
  --sha "$RELEASE_SHA" \
  --version "$RELEASE_VERSION" \
  --out docs/quality-metrics.md \
  "${CHART_ARGS[@]}" \
  "${MUTATION_ARGS[@]}"
