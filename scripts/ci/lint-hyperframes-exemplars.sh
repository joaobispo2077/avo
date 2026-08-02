#!/usr/bin/env bash
# Lint committed HyperFrames exemplar compositions (authoring sources only — no mp4).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

EXEMPLARS=(
  "docs/exemplars/hyperframes-product-promo/starter"
  "docs/exemplars/hyperframes-short-form/starter"
  "docs/exemplars/hyperframes-boil-insert/starter"
  "docs/exemplars/hyperframes-boil-insert/starter-image"
)

for dir in "${EXEMPLARS[@]}"; do
  if [[ ! -f "$dir/index.html" ]]; then
    echo "Missing exemplar: $dir/index.html" >&2
    exit 1
  fi
  echo "==> hyperframes lint: $dir"
  (cd "$dir" && npm exec -- hyperframes lint)
done

echo "All HyperFrames exemplars passed lint."
