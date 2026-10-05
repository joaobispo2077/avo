#!/usr/bin/env bash
# Duplication gate: jscpd on src/avo with threshold from .jscpd.json (task-015).
# Baseline 2026-08-14: ~1.09% duplicated lines; threshold 2% (fail-immediately over threshold).
# No soft/warn mode. No separate quality.yml (spec v1.4).
# The JSON file is the percentage jscpd already computed, so the sticky chart
# can draw it. The threshold stays in .jscpd.json.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

mkdir -p reports/quality/jscpd
exec npx --no-install jscpd \
  --config .jscpd.json \
  --reporters console,json \
  --output reports/quality/jscpd
