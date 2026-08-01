#!/usr/bin/env bash
# AVO — bootstrap a per-video project (avo.project.json) in an external raw dir.
# Thin wrapper over helpers/init_project.py (shared cross-platform logic).
#
# Usage:
#   bash scripts/init-project.sh --provider bishop --raw-dir /abs/path/to/footage \
#        [--title T] [--sfx P] [--music P] [--inserts P] [--graphics P] \
#        [--lang CODE] [--print] [--yes]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo "error: python3 not found on PATH" >&2; exit 1; fi
fi

exec "$PY" "$REPO_ROOT/helpers/init_project.py" "$@"
