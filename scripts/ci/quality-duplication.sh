#!/usr/bin/env bash
# Duplication gate: jscpd on src/avo with threshold from .jscpd.json (task-015).
# Baseline 2026-08-14: ~1.09% duplicated lines; threshold 2% (fail-immediately over threshold).
# No soft/warn mode. No separate quality.yml (spec v1.4).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

exec npx --no-install jscpd --config .jscpd.json
