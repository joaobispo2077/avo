#!/usr/bin/env bash
# AVO — scaffold a new provider workspace from providers/_template/.
# Cross-platform: POSIX bash (macOS / Linux / WSL). Windows users use
# scripts/new-provider.ps1.
#
# Usage:
#   bash scripts/new-provider.sh <name> [--kind KIND] [--raw-root PATH]
#        [--sfx PATH] [--music PATH] [--inserts PATH] [--graphics PATH]
#        [--lang CODE] [--yes]
#
# Missing required values are prompted for when running interactively.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
TEMPLATE_DIR="$REPO_ROOT/providers/_template"

VALID_KINDS="youtube tiktok instagram x podcast shorts generic"

NAME=""
KIND=""
RAW_ROOT=""
SFX=""
MUSIC=""
INSERTS=""
GRAPHICS=""
LANG_CODE="en"
ASSUME_YES=0

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
}

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --kind)      KIND="${2:-}"; shift 2;;
    --raw-root)  RAW_ROOT="${2:-}"; shift 2;;
    --sfx)       SFX="${2:-}"; shift 2;;
    --music)     MUSIC="${2:-}"; shift 2;;
    --inserts)   INSERTS="${2:-}"; shift 2;;
    --graphics)  GRAPHICS="${2:-}"; shift 2;;
    --lang)      LANG_CODE="${2:-}"; shift 2;;
    --yes|-y)    ASSUME_YES=1; shift;;
    -h|--help)   usage; exit 0;;
    --*)         die "unknown option: $1";;
    *)
      if [ -z "$NAME" ]; then NAME="$1"; shift; else die "unexpected argument: $1"; fi;;
  esac
done

[ -d "$TEMPLATE_DIR" ] || die "template not found: $TEMPLATE_DIR"

prompt() { # prompt VAR "message" "default"
  local __var="$1" __msg="$2" __def="${3:-}" __ans=""
  if [ -t 0 ]; then
    if [ -n "$__def" ]; then
      read -r -p "$__msg [$__def]: " __ans || true
      __ans="${__ans:-$__def}"
    else
      read -r -p "$__msg: " __ans || true
    fi
  else
    __ans="$__def"
  fi
  printf -v "$__var" '%s' "$__ans"
}

[ -n "$NAME" ] || prompt NAME "Provider slug (lowercase kebab-case)"
[ -n "$NAME" ] || die "provider name is required"
printf '%s' "$NAME" | grep -Eq '^[a-z0-9][a-z0-9-]*$' \
  || die "invalid name '$NAME' (use lowercase letters, digits, hyphens)"

[ -n "$KIND" ] || prompt KIND "Kind ($VALID_KINDS)" "youtube"
case " $VALID_KINDS " in *" $KIND "*) : ;; *) die "invalid kind '$KIND' (one of: $VALID_KINDS)";; esac

[ -n "$RAW_ROOT" ] || prompt RAW_ROOT "External raw footage root (absolute path, NOT inside this repo)"
[ -n "$RAW_ROOT" ] || die "raw footage root is required"

# Optional asset dirs (only prompted interactively).
[ -n "$SFX" ]      || prompt SFX "External SFX library path (optional)" ""
[ -n "$MUSIC" ]    || prompt MUSIC "External music library path (optional)" ""
[ -n "$INSERTS" ]  || prompt INSERTS "External inserts/b-roll path (optional)" ""
[ -n "$GRAPHICS" ] || prompt GRAPHICS "External graphics/overlays path (optional)" ""

DEST="$REPO_ROOT/providers/$NAME"
[ -e "$DEST" ] && die "provider already exists: providers/$NAME"

json_escape() { # escape backslash and double-quote for JSON string values
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

mkdir -p "$DEST/logo" "$DEST/brand"
cp "$TEMPLATE_DIR/DESIGN.md" "$DEST/DESIGN.md"
cp "$TEMPLATE_DIR/brand/palette.json" "$DEST/brand/palette.json"
cp "$TEMPLATE_DIR/logo/.gitkeep" "$DEST/logo/.gitkeep"

cat > "$DEST/avo.provider.json" <<JSON
{
  "\$schema": "../avo.provider.schema.json",
  "name": "$(json_escape "$NAME")",
  "displayName": "$(json_escape "$NAME")",
  "kind": "$(json_escape "$KIND")",
  "description": "",
  "media": {
    "rawRoot": "$(json_escape "$RAW_ROOT")"
  },
  "assets": {
    "sfx": "$(json_escape "$SFX")",
    "music": "$(json_escape "$MUSIC")",
    "inserts": "$(json_escape "$INSERTS")",
    "graphics": "$(json_escape "$GRAPHICS")",
    "logos": "providers/$(json_escape "$NAME")/logo"
  },
  "transcription": {
    "language": "$(json_escape "$LANG_CODE")"
  },
  "brand": {
    "design": "providers/$(json_escape "$NAME")/DESIGN.md",
    "palette": "providers/$(json_escape "$NAME")/brand/palette.json"
  },
  "routingOverrides": {}
}
JSON

printf 'Created provider workspace: providers/%s\n' "$NAME"
printf '  manifest : providers/%s/avo.provider.json\n' "$NAME"
printf '  design   : providers/%s/DESIGN.md\n' "$NAME"
printf '  logo/    : add SVG source + PNG exports\n'
printf '  brand/   : edit palette.json\n'
printf '\nNext: edit DESIGN.md and brand/palette.json; media stays external at:\n  %s\n' "$RAW_ROOT"
