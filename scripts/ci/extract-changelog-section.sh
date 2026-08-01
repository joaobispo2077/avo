#!/usr/bin/env bash
# Print the CHANGELOG.md body for a SemVer release (excludes the heading line).
# Usage: extract-changelog-section.sh 0.1.0
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "error: version argument required (e.g. 0.1.0)" >&2
  exit 1
fi

python - "$VERSION" "$ROOT/CHANGELOG.md" <<'PY'
import sys
from pathlib import Path

version = sys.argv[1]
path = Path(sys.argv[2])
text = path.read_text(encoding="utf-8")
heading = f"## [{version}]"
start = text.find(heading)
if start < 0:
    print(f"error: section {heading} not found in CHANGELOG.md", file=sys.stderr)
    sys.exit(1)
rest = text[start + len(heading) :].lstrip("\n\r")
end = rest.find("\n## ")
body = rest if end < 0 else rest[:end]
body = body.rstrip()
if not body:
    print(f"error: empty changelog section for {version}", file=sys.stderr)
    sys.exit(1)
print(body)
PY
