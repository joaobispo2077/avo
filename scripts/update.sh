#!/usr/bin/env bash
# AVO — self-update: git pull (ff-only) + full skills/toolchain refresh.
# Preserves gitignored provider workspaces under providers/<slug>/.
#
# Usage: bash scripts/update.sh [check|apply] [--yes] [--dry-run] [--json] [--skip-sync]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
cd "$REPO_ROOT"

PY=""
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python; fi

if [ -z "$PY" ]; then
  echo "AVO update: python not found" >&2
  exit 1
fi

CMD="apply"
ARGS=()
if [ $# -gt 0 ] && { [ "$1" = "check" ] || [ "$1" = "apply" ]; }; then
  CMD="$1"
  shift
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PY" -m avo.update "$CMD" "$@"
