#!/usr/bin/env bash
# Dependency security: pip-audit + npm audit high+ (task-011 / FR-6).
# Fail-immediately — no warn-only. Documented exceptions live in
# deps-audit-allowlist.json (npm GHSA ids; pip ignore list via pip-audit flags).
# Requires network + tooling installed (uv sync --frozen --extra dev; npm ci).
# Spec v1.4: wired from ci.yml software-quality — never quality.yml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
CI_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> quality:deps (pip-audit)"
# Optional documented CVE/GHSA ignores from allowlist (empty by default).
mapfile -t PIP_IGNORE_IDS < <(
  uv run --frozen --extra dev python - <<'PY'
import json
from pathlib import Path
raw = json.loads(Path("scripts/ci/deps-audit-allowlist.json").read_text(encoding="utf-8"))
for item in raw.get("pip", {}).get("ignore_vulns", []):
    vuln_id = item.get("id") if isinstance(item, dict) else item
    if vuln_id:
        print(vuln_id)
PY
)
PIP_IGNORE_ARGS=()
for vuln in "${PIP_IGNORE_IDS[@]+"${PIP_IGNORE_IDS[@]}"}"; do
  [[ -n "$vuln" ]] || continue
  PIP_IGNORE_ARGS+=(--ignore-vuln "$vuln")
done
# --skip-editable: audit third-party deps only (local avo is not on PyPI).
uv run --frozen --extra dev pip-audit --skip-editable "${PIP_IGNORE_ARGS[@]}"

echo "==> quality:deps (npm audit high+ via check_npm_audit.py)"
uv run --frozen --extra dev python "$CI_DIR/check_npm_audit.py"

echo "quality:deps passed."
