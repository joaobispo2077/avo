#!/usr/bin/env bash
# Dependency tree health (task-017 / FR-10): npm find-dupes (dedupe dry-run).
# Reports hoist/dupe plan against the committed lockfile. Command failure fails
# the gate; a non-empty dry-run plan is report-only until a zero-diff baseline
# is promoted via /evolve. Spec v1.4: ci.yml software-quality — never quality.yml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:tree (npm find-dupes — lockfile dry-run report)"
npm find-dupes --ignore-scripts --no-fund --no-audit

echo "quality:tree passed (find-dupes completed; dry-run plan is report-only)."
