#!/usr/bin/env bash
# Maintainer smoke: full setup contract on Linux CI (may download Whisper model).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd)"
cd "$REPO_ROOT"
bash scripts/setup.sh --yes --lang en --skip remotion
bash scripts/validate-prerequisites.sh --include-optional
bash scripts/validate-usability.sh
