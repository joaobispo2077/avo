#!/usr/bin/env bash
# Informational pack/install footprint (task-020). Always exit 0.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

OUT="${1:-size-signal-raw.txt}"
{
  echo "npm pack --dry-run"
  npm pack --dry-run || true
  echo
  echo "du -sh node_modules (install footprint proxy)"
  du -sh node_modules 2>/dev/null || echo "(node_modules size unavailable)"
} > "$OUT" 2>&1
exit 0
