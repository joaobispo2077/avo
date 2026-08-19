#!/usr/bin/env bash
# Software-quality umbrella (Phase 1 Must Have + Phase 2 deadcode/architecture). Additive to Gate 1/2.
# Mirrors npm run quality. Lint/format fail-immediately (task-008 / ci.yml);
# coverage fail-under (task-009); complexity xenon B + allowlist + C901 (task-010);
# deps pip-audit + npm audit high+ fail-immediately (task-011);
# deadcode vulture + allowlist fail-immediately (task-014 / FR-8);
# architecture import-linter contracts fail-immediately (task-016 / FR-9).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
CI_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> quality (fast gates)"
bash "$CI_DIR/quality-lint.sh"
bash "$CI_DIR/quality-format.sh"
bash "$CI_DIR/run-coverage.sh"
bash "$CI_DIR/quality-complexity.sh"
bash "$CI_DIR/quality-deps.sh"
bash "$CI_DIR/quality-deadcode.sh"
bash "$CI_DIR/quality-duplication.sh"
bash "$CI_DIR/quality-architecture.sh"
bash "$CI_DIR/quality-tree.sh"
echo "quality umbrella finished."
