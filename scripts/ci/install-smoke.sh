#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
node bin/install.cjs --dry-run --only cursor
bash scripts/install/install.sh --dry-run --only cursor 2>/dev/null || true
