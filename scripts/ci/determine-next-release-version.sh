#!/usr/bin/env bash
# Extract the next semantic-release version from a dry-run (CI gate before publish).
# Writes next-version to GITHUB_OUTPUT when set; prints human-readable status to stdout.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

OUTPUT=""
STATUS=0
set +e
OUTPUT="$(env -u GITHUB_ACTIONS npx semantic-release --dry-run 2>&1)"
STATUS=$?
set -e

printf '%s\n' "$OUTPUT"

write_outputs() {
  local next="${1:-}"
  local dry_exit="${2:-0}"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
      echo "next-version=${next}"
      echo "dry-run-exit=${dry_exit}"
    } >> "$GITHUB_OUTPUT"
  fi
}

if printf '%s\n' "$OUTPUT" | grep -qiE "won.t be published"; then
  echo "semantic-release will not publish on this ref; release job will be skipped."
  write_outputs "" "$STATUS"
  exit 0
fi

NEXT=""
MATCH="$(printf '%s\n' "$OUTPUT" | grep -im1 -Eo 'the next release version is [^[:space:]]+' || true)"
if [ -n "$MATCH" ]; then
  NEXT="${MATCH##* is }"
  NEXT="${NEXT%%(*}"
  NEXT="${NEXT%%)}"
fi

if [ -z "$NEXT" ]; then
  echo "No releasable version found in semantic-release dry-run; release job will be skipped."
  write_outputs "" "$STATUS"
  if [ "$STATUS" -ne 0 ]; then
    echo "semantic-release --dry-run exited ${STATUS}; see log above." >&2
  fi
  exit 0
fi

write_outputs "$NEXT" "$STATUS"
echo "Next release version: ${NEXT}"
