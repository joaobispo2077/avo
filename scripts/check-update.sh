#!/usr/bin/env bash
# AVO — weekly update check (macOS / Linux / WSL).
# Reads lastUpdateCheck from .avo/state.json; if >= N days (default 7), fetches,
# compares against upstream, offers a fast-forward pull, and rewrites the
# timestamp. Skips cleanly on a dirty working tree or when offline (never
# clobbers local changes).
#
# Usage: bash scripts/check-update.sh [--days N] [--force] [--yes] [--quiet]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
cd "$REPO_ROOT"

DAYS=7
FORCE=0
ASSUME_YES=0
QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --days)  DAYS="${2:-7}"; shift 2;;
    --force) FORCE=1; shift;;
    --yes|-y) ASSUME_YES=1; shift;;
    --quiet) QUIET=1; shift;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done

say()  { [ "$QUIET" -eq 1 ] || echo "$@"; }
warn() { echo "AVO update: $*" >&2; }

PY=""
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python; fi

# --- is a check due? ---------------------------------------------------------
if [ "$FORCE" -ne 1 ] && [ -n "$PY" ]; then
  DUE_OUT="$(PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" "$PY" -m avo.avo_state due --days "$DAYS" 2>/dev/null || echo 'due unknown')"
  case "$DUE_OUT" in
    recent*) say "AVO update: checked recently (${DUE_OUT#recent }); use --force to check now."; exit 0;;
  esac
fi

# --- preflight ---------------------------------------------------------------
if ! command -v git >/dev/null 2>&1; then warn "git not found; skipping."; exit 0; fi
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then warn "not a git repo; skipping."; exit 0; fi

# --- dirty tree? (warn, don't clobber) --------------------------------------
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  warn "working tree has local changes — skipping update (won't clobber). Commit/stash, then rerun."
  exit 0
fi

# --- fetch (offline => skip) -------------------------------------------------
if ! git fetch --quiet 2>/dev/null; then
  warn "fetch failed (offline?) — skipping. Will retry next session."
  exit 0
fi

touch_ts() { [ -n "$PY" ] && PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" "$PY" -m avo.avo_state touch-update >/dev/null 2>&1 || true; }

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  warn "no upstream tracking branch for '$BRANCH' — skipping compare."; touch_ts; exit 0
fi

BEHIND="$(git rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)"
AHEAD="$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"

if [ "${BEHIND:-0}" -eq 0 ]; then
  say "AVO update: up to date on '$BRANCH'."
  touch_ts
  exit 0
fi

say "AVO update: $BEHIND new commit(s) available on '$BRANCH' (local ahead: ${AHEAD:-0})."
DO_PULL=0
if [ "$ASSUME_YES" -eq 1 ]; then
  DO_PULL=1
elif [ -t 0 ]; then
  read -r -p "Pull latest (fast-forward only)? [y/N]: " ans || true
  case "$ans" in y|Y|yes|YES) DO_PULL=1;; esac
fi

if [ "$DO_PULL" -eq 1 ]; then
  if git pull --ff-only --quiet; then
    say "AVO update: pulled latest on '$BRANCH'."
    touch_ts
  else
    warn "fast-forward pull failed (diverged?) — resolve manually. Not clobbering."
  fi
else
  say "AVO update: skipped pull. Run 'git pull --ff-only' when ready."
  # Still stamp the check so we don't nag every session; update is available.
  touch_ts
fi
