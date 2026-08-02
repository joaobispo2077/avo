#!/usr/bin/env bash
# Extract the next semantic-release version from a dry-run (CI gate before publish).
# Writes next-version to GITHUB_OUTPUT when set; prints human-readable status to stdout.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

OUTPUT=""
STATUS=0
set +e
OUTPUT="$(npx semantic-release --dry-run 2>&1)"
STATUS=$?
set -e

printf '%s\n' "$OUTPUT"

NEXT=""
while IFS= read -r line; do
  case "$line" in
    *"The next release version is "*)
      NEXT="${line##*The next release version is }"
      NEXT="${NEXT%% *}"
      break
      ;;
  esac
done <<< "$OUTPUT"

if [ -z "$NEXT" ]; then
  NEXT="$(printf '%s\n' "$OUTPUT" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?' | head -1 || true)"
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "next-version=${NEXT}"
    echo "dry-run-exit=${STATUS}"
  } >> "$GITHUB_OUTPUT"
fi

if [ -z "$NEXT" ]; then
  echo "No releasable commits found; release job will be skipped."
  if [ "$STATUS" -ne 0 ]; then
    echo "semantic-release --dry-run exited ${STATUS}; see log above." >&2
  fi
  exit 0
fi

echo "Next release version: ${NEXT}"
