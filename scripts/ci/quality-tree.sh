#!/usr/bin/env bash
# Dependency tree health (task-017 / FR-10): npm find-dupes (dedupe dry-run).
# Reports hoist/dupe plan against the committed lockfile. Command failure fails
# the gate; a non-empty dry-run plan is report-only until a zero-diff baseline
# is promoted via /evolve. Spec v1.4: ci.yml software-quality — never quality.yml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> quality:tree (npm find-dupes — lockfile dry-run report)"
mkdir -p reports/quality
status=0
npm find-dupes --ignore-scripts --no-fund --no-audit --json > reports/quality/dependency-tree-raw.log || status=$?
cat reports/quality/dependency-tree-raw.log
if [[ "$status" -ne 0 ]]; then exit "$status"; fi
# npm prints the proposed plan before its JSON document, even with --json.
python -c 'import json; from pathlib import Path; raw = Path("reports/quality/dependency-tree-raw.log").read_text(encoding="utf-8"); data = json.loads(raw[raw.index("{"):]); Path("reports/quality/dependency-tree.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")'

echo "quality:tree passed (find-dupes completed; dry-run plan is report-only)."
