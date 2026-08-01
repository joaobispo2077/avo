#!/usr/bin/env bash
# AVO installer shim (bash). Delegates to bin/install.js or npx github:REPO.
#
# curl -fsSL https://raw.githubusercontent.com/joaobispo2077/avo/main/install.sh | bash
# bash install.sh [--dry-run] [--full] [--lang en] [--only cursor]

set -euo pipefail

REPO="${AVO_INSTALL_REPO:-joaobispo2077/avo}"

if ! command -v node >/dev/null 2>&1; then
  echo "AVO: Node.js (≥18) required. Install from https://nodejs.org" >&2
  exit 1
fi

NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]")"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "AVO: Node $NODE_MAJOR too old. Need Node ≥18." >&2
  exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" 2>/dev/null && pwd)" || here=""
if [ -n "$here" ] && [ -f "$here/bin/install.cjs" ]; then
  exec node "$here/bin/install.cjs" "$@"
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "AVO: npx required (ships with Node ≥18)." >&2
  exit 1
fi

exec npx -y "github:${REPO}" "$@"
