#!/usr/bin/env bash
# AVO installer (bash). Delegates to bin/install.cjs (skills + engine zip).
# npx skills add does NOT download the engine zip — this script does.
#
# curl -fsSL https://raw.githubusercontent.com/joaobispo2077/avo/main/scripts/install/install.sh | bash
# bash scripts/install/install.sh [--dry-run] [--full] [--lang en] [--only cursor]

set -euo pipefail

REPO="${AVO_INSTALL_REPO:-joaobispo2077/avo}"
REF="${AVO_INSTALL_REF:-main}"

if ! command -v node >/dev/null 2>&1; then
  echo "AVO: Node.js (≥18) required. Install from https://nodejs.org" >&2
  exit 1
fi

NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]")"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "AVO: Node $NODE_MAJOR too old. Need Node ≥18." >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
if [ -f "$repo_root/bin/install.cjs" ]; then
  exec node "$repo_root/bin/install.cjs" "$@"
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "AVO: curl required to fetch bin/install.cjs." >&2
  exit 1
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "https://raw.githubusercontent.com/${REPO}/${REF}/bin/install.cjs" -o "$tmp"
exec node "$tmp" "$@"
