#!/usr/bin/env bash
# Gate 1 — orchestrator prerequisites (video-use, watch-skill, HyperFrames, …)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
cd "$REPO_ROOT"
PY="${PY:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then PY=python; fi
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PY" -m avo.validate_dependencies "$@"
