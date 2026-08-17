#!/usr/bin/env bash
# Alias used by mutation-full.yml (task-018).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export AVO_MUTATION_PROFILE="${AVO_MUTATION_PROFILE:-full}"
exec bash "$ROOT/scripts/ci/quality-mutation.sh"
