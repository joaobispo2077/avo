#!/usr/bin/env bash
# =============================================================================
# AVO — AI Video Orchestrator :: setup (macOS / Linux / WSL)
# -----------------------------------------------------------------------------
# Prepares the toolchain AVO orchestrates. Native primary entrypoint.
# Idempotent: re-running skips already-satisfied steps. Optional tools never
# fail the run.
#
# Usage:
#   bash scripts/setup.sh [--lang CODE] [--model SIZE]
#                         [--with-memory] [--with-jail] [--with-logo]
#                         [--with-upstream-ref]
#                         [--skip TOOL]... [--yes] [--dry-run]
#
# Flags:
#   --lang CODE     faster-whisper transcription language (e.g. pt, en, es).
#   --model SIZE    Whisper model size to prepare (default: small).
#   --with-memory   Install ai-memory (optional cross-session memory).
#   --with-jail     Install ai-jail (optional; Linux/macOS native; WSL2 on Windows).
#   --with-logo     Install logo-generator-skill (optional brand assets).
#   --with-upstream-ref  Sync tools/video-use-upstream/ for maintainer diffs (optional).
#   --skip TOOL     Skip a step: speckit|engine|watch|hyperframes|remotion (repeatable).
#   --yes, -y       Non-interactive; accept defaults, no prompts.
#   --dry-run       Print actions without executing.
#   -h, --help      Show this help.
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
cd "$REPO_ROOT"

LANG_CODE=""
MODEL_SIZE="small"
WITH_MEMORY=0
WITH_JAIL=0
WITH_LOGO=0
WITH_UPSTREAM_REF=0
ASSUME_YES=0
DRY_RUN=0
declare -a SKIP=()

usage() { sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --lang)        LANG_CODE="${2:-}"; shift 2;;
    --model)       MODEL_SIZE="${2:-small}"; shift 2;;
    --with-memory) WITH_MEMORY=1; shift;;
    --with-jail)   WITH_JAIL=1; shift;;
    --with-logo)   WITH_LOGO=1; shift;;
    --with-upstream-ref) WITH_UPSTREAM_REF=1; shift;;
    --skip)        SKIP+=("${2:-}"); shift 2;;
    --yes|-y)      ASSUME_YES=1; shift;;
    --dry-run)     DRY_RUN=1; shift;;
    -h|--help)     usage; exit 0;;
    *) echo "unknown option: $1" >&2; usage; exit 1;;
  esac
done

# ---- output helpers ---------------------------------------------------------
declare -a RESULTS=()
c_reset=$'\033[0m'; c_dim=$'\033[2m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_red=$'\033[31m'; c_cyn=$'\033[36m'
[ -t 1 ] || { c_reset=""; c_dim=""; c_grn=""; c_yel=""; c_red=""; c_cyn=""; }

step()  { printf '\n%s==>%s %s\n' "$c_cyn" "$c_reset" "$1"; }
info()  { printf '    %s%s%s\n' "$c_dim" "$1" "$c_reset"; }
record() { RESULTS+=("$1|$2|$3"); }   # tool|status|note
have()  { command -v "$1" >/dev/null 2>&1; }
skipped() { local t; for t in "${SKIP[@]:-}"; do [ "$t" = "$1" ] && return 0; done; return 1; }

run() { # echo + execute (honors --dry-run). Returns command exit code.
  info "\$ $*"
  if [ "$DRY_RUN" -eq 1 ]; then return 0; fi
  "$@"
}

PY=""
pick_python() {
  if have python3; then PY=python3; elif have python; then PY=python; fi
}

# ---- 0. Preflight -----------------------------------------------------------
step "Preflight"
UNAME="$(uname -s 2>/dev/null || echo unknown)"
IS_WSL=0
if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then IS_WSL=1; fi
info "OS: $UNAME  WSL: $IS_WSL  dry-run: $DRY_RUN"
pick_python
if [ -n "$PY" ]; then record python OK "$($PY --version 2>&1)"; else record python FAIL "not found"; fi
if have node; then record node OK "$(node --version)"; else record node WARN "not found (motion tools need Node >=18)"; fi
if have npm;  then record npm OK "$(npm --version)"; else record npm WARN "not found"; fi
if have git;  then record git OK "$(git --version)"; else record git WARN "not found"; fi

# ---- prompt for language ----------------------------------------------------
if [ -z "$LANG_CODE" ]; then
  if [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
    read -r -p "Transcription language code (faster-whisper, e.g. pt/en/es) [en]: " LANG_CODE || true
  fi
  LANG_CODE="${LANG_CODE:-en}"
fi
info "transcription language: $LANG_CODE"

# ---- 1. GitHub Spec Kit -----------------------------------------------------
if skipped speckit; then record speckit SKIP "--skip speckit"; else
  step "GitHub Spec Kit (.specify)"
  if [ -d "$REPO_ROOT/.specify" ]; then
    record speckit OK "GitHub Spec Kit present"
  else
    record speckit WARN "GitHub Spec Kit not detected — run 'specify init' or see https://github.com/github/spec-kit"
  fi
fi

# ---- 2. video-use engine ----------------------------------------------------
if skipped engine; then record engine SKIP "--skip engine"; else
  step "video-use engine (Python deps + ffmpeg + Whisper model)"
  if [ -z "$PY" ]; then
    record engine FAIL "python not available"
  else
    if have uv; then run uv sync; else run "$PY" -m pip install -e .; fi
    if have ffmpeg && have ffprobe; then
      record ffmpeg OK "on PATH"
    else
      record ffmpeg WARN "ffmpeg/ffprobe not on PATH (Node ffmpeg-static is a fallback)"
      info "install: macOS 'brew install ffmpeg' · Debian/Ubuntu 'sudo apt-get install -y ffmpeg' · Arch 'sudo pacman -S ffmpeg'"
    fi
    export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
    run "$PY" -m avo.avo_state init --language "$LANG_CODE" --whisper-model "$MODEL_SIZE" --touch-update
    if run "$PY" -m avo.prepare_transcription --model "$MODEL_SIZE"; then
      record engine OK "deps + model '$MODEL_SIZE' (lang $LANG_CODE)"
      if run "$PY" -m avo.models_cli disclosure; then
        record models OK "active models disclosed"
      else
        record models WARN "model disclosure skipped"
      fi
    else
      record engine WARN "deps ok; model prep incomplete (offline?) — rerun python -m avo.prepare_transcription"
    fi
  fi
fi

# ---- 3. watch-skill ---------------------------------------------------------
if skipped watch; then record watch SKIP "--skip watch"; else
  step "watch-skill (THE LOOP — understand/verify)"
  WS_DIR="$REPO_ROOT/tools/watch-skill"
  if [ -d "$WS_DIR/.git" ]; then
    ( run git -C "$WS_DIR" pull --ff-only ) && record watch OK "updated $WS_DIR" || record watch WARN "present; update failed (offline?)"
  elif have git; then
    if run git clone https://github.com/oxbshw/watch-skill "$WS_DIR"; then
      record watch OK "cloned to $WS_DIR"
    else
      record watch WARN "clone failed (offline?) — see https://github.com/oxbshw/watch-skill"
    fi
  else
    record watch WARN "git missing — clone https://github.com/oxbshw/watch-skill manually"
  fi
fi

# ---- 4. HyperFrames ---------------------------------------------------------
if skipped hyperframes; then record hyperframes SKIP "--skip hyperframes"; else
  step "HyperFrames (default motion engine)"
  if have npm; then
    if run npm install; then
      if run npx --no-install hyperframes doctor; then
        record hyperframes OK "npm install + doctor"
      else
        record hyperframes WARN "installed; 'hyperframes doctor' reported issues"
      fi
    else
      record hyperframes WARN "npm install failed (offline?)"
    fi
  else
    record hyperframes WARN "npm missing (need Node >=18)"
  fi
fi

# ---- 5. Remotion ------------------------------------------------------------
if skipped remotion; then record remotion SKIP "--skip remotion"; else
  step "Remotion (alternate motion engine)"
  record remotion OK "installed per-project when needed (see docs/remotion-decision-guide.md)"
fi

# ---- 6. ai-memory (optional) ------------------------------------------------
if [ "$WITH_MEMORY" -eq 1 ]; then
  step "ai-memory (optional cross-session memory)"
  if have git; then
    MEM_DIR="$REPO_ROOT/tools/ai-memory"
    if [ -d "$MEM_DIR/.git" ]; then
      run git -C "$MEM_DIR" pull --ff-only && record ai-memory OK "updated" || record ai-memory WARN "update failed"
    elif run git clone https://github.com/akitaonrails/ai-memory "$MEM_DIR"; then
      record ai-memory OK "cloned to $MEM_DIR (runs zero-LLM by default)"
    else
      record ai-memory WARN "clone failed — see https://github.com/akitaonrails/ai-memory"
    fi
  else
    record ai-memory WARN "git missing"
  fi
else
  record ai-memory SKIP "enable with --with-memory"
fi

# ---- 7. ai-jail (optional; Linux/macOS native; WSL2 on Windows) --------------
if [ "$WITH_JAIL" -eq 1 ]; then
  step "ai-jail (optional agent sandbox)"
  UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
  if [ "$UNAME_S" = "Linux" ]; then
    if have bwrap; then
      record bwrap OK "on PATH ($(command -v bwrap))"
    else
      record bwrap WARN "missing — install bubblewrap (e.g. apt install bubblewrap)"
      info "Ubuntu 24.04+ AppArmor userns: see https://github.com/akitaonrails/ai-jail#ubuntu-2404--debian-13-users"
    fi
  elif [ "$UNAME_S" = "Darwin" ]; then
    info "macOS uses sandbox-exec (system); no bubblewrap required"
  fi
  if have ai-jail; then
    if run ai-jail --version >/dev/null 2>&1; then
      record ai-jail OK "already installed ($(command -v ai-jail))"
    else
      record ai-jail WARN "binary found but ai-jail --version failed"
    fi
  elif have brew; then
    run brew install akitaonrails/tap/ai-jail && record ai-jail OK "via brew" || record ai-jail WARN "brew install failed — see https://github.com/akitaonrails/ai-jail"
  elif have cargo; then
    run cargo install ai-jail && record ai-jail OK "via cargo" || record ai-jail WARN "cargo install failed"
  elif have mise; then
    run mise use -g ai-jail && record ai-jail OK "via mise" || record ai-jail WARN "mise install failed"
  elif have nix; then
    info "nix detected: install ai-jail via your flake/profile (nix profile install github:akitaonrails/ai-jail)"
    record ai-jail WARN "install via nix manually"
  else
    record ai-jail WARN "no supported installer — try GitHub Releases: https://github.com/akitaonrails/ai-jail/releases"
  fi
  info "Sandbox tips: mask secrets (e.g. --mask .env); map the EXTERNAL media root read-write."
  info "Operator guide: docs/ai-memory-and-ai-jail.md"
else
  record ai-jail SKIP "enable with --with-jail (optional; Linux/macOS native, WSL2 on Windows)"
fi

# ---- 8. logo-generator-skill (optional) -------------------------------------
if [ "$WITH_LOGO" -eq 1 ]; then
  step "logo-generator-skill (optional brand assets)"
  if have git; then
    LOGO_DIR="$REPO_ROOT/tools/logo-generator-skill"
    if [ -d "$LOGO_DIR/.git" ]; then
      run git -C "$LOGO_DIR" pull --ff-only && record logo OK "updated" || record logo WARN "update failed"
    elif run git clone https://github.com/op7418/logo-generator-skill "$LOGO_DIR"; then
      record logo OK "cloned (SVG path keyless; showcase needs GEMINI_API_KEY)"
    else
      record logo WARN "clone failed — see https://github.com/op7418/logo-generator-skill"
    fi
  else
    record logo WARN "git missing"
  fi
else
  record logo SKIP "enable with --with-logo"
fi

# ---- video-use upstream ref (optional, maintainer) ---------------------------
if [ "$WITH_UPSTREAM_REF" -eq 1 ]; then
  step "video-use upstream reference (maintainer diff)"
  if run bash "$REPO_ROOT/scripts/upstream/sync-video-use-upstream.sh"; then
    record upstream-ref OK "tools/video-use-upstream"
  else
    record upstream-ref WARN "sync failed (offline?) — run scripts/upstream/sync-video-use-upstream.sh"
  fi
else
  record upstream-ref SKIP "enable with --with-upstream-ref"
fi

# ---- Summary ----------------------------------------------------------------
step "Setup summary"
fail_count=0
printf '    %-14s %-6s %s\n' "TOOL" "STATUS" "NOTE"
printf '    %-14s %-6s %s\n' "----" "------" "----"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r tool status note <<<"$row"
  case "$status" in
    OK)   col="$c_grn";;
    WARN) col="$c_yel";;
    SKIP) col="$c_dim";;
    FAIL) col="$c_red"; fail_count=$((fail_count+1));;
    *)    col="$c_reset";;
  esac
  printf '    %-14s %s%-6s%s %s\n' "$tool" "$col" "$status" "$c_reset" "$note"
done

echo
if [ "$fail_count" -gt 0 ]; then
  printf '%sSetup finished with %d failure(s).%s Resolve FAIL rows above.\n' "$c_red" "$fail_count" "$c_reset"
  exit 1
fi
printf '%sSetup complete.%s Optional WARN rows are safe to ignore or address later.\n' "$c_grn" "$c_reset"
