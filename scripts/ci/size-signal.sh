#!/usr/bin/env bash
# Informational pack/install footprint (task-020). Always exit 0.
# Writes a short markdown summary — not the npm pack file listing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

OUT="${1:-size-signal-report.md}"
python scripts/ci/write_size_signal_report.py --out "$OUT" || {
  {
    echo "## Size signal"
    echo
    echo "- Status: **SIGNAL ERROR (informational only)**"
    echo "- Policy: **non-blocking**"
    echo
    echo "Failed to summarize \`npm pack --dry-run --json\`."
  } > "$OUT"
}
exit 0
