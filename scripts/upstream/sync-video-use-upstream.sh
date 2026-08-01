#!/usr/bin/env bash
# Sync browser-use/video-use reference clone for maintainer diffs (optional).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd)"
DEST="$REPO_ROOT/tools/video-use-upstream"
REPO="https://github.com/browser-use/video-use"
REF=""
DRY_RUN=0

usage() {
  sed -n '1,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:-}"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done

if [ -z "$REF" ]; then
  REF="$(git ls-remote --tags "$REPO" 2>/dev/null | awk -F/ '{print $3}' | grep -E '^v[0-9]' | sort -V | tail -1 || true)"
  if [ -z "$REF" ]; then
    REF="main"
  fi
fi

echo "upstream ref: $REF"
echo "destination: $DEST"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] would sync $REPO @ $REF -> $DEST"
  exit 0
fi

mkdir -p "$(dirname "$DEST")"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch --depth 1 origin "$REF" 2>/dev/null || git -C "$DEST" fetch origin
  git -C "$DEST" checkout -q FETCH_HEAD 2>/dev/null || git -C "$DEST" checkout -q "$REF"
else
  rm -rf "$DEST"
  git clone --depth 1 --branch "$REF" "$REPO" "$DEST" 2>/dev/null || {
    rm -rf "$DEST"
    git clone --depth 1 "$REPO" "$DEST"
    git -C "$DEST" checkout -q "$REF"
  }
fi

SHA="$(git -C "$DEST" rev-parse HEAD)"
PIN="$DEST/.avo-upstream-pin.json"
python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
pin = {
    "repo": "$REPO",
    "ref": "$REF",
    "sha": "$SHA",
    "syncedAt": datetime.now(timezone.utc).isoformat(),
}
Path("$PIN").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
print(json.dumps(pin))
PY

echo "synced $REF ($SHA)"
