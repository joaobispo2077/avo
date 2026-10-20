#!/usr/bin/env bash
# Unpack a frozen engine zip and smoke the public CLI. Transcribe stub must not skip.
# ffmpeg-full verbs may skip if ffmpeg is absent; --help still runs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "error: python3/python not found" >&2
  exit 1
fi

if [[ -n "${AVO_ENGINE_PLATFORM:-}" ]]; then
  PLATFORM="$AVO_ENGINE_PLATFORM"
elif [[ "${RUNNER_OS:-}" == "Windows" ]]; then
  PLATFORM="windows-x64"
elif [[ "${RUNNER_OS:-}" == "macOS" ]]; then
  PLATFORM="macos-arm64"
elif [[ "${RUNNER_OS:-}" == "Linux" ]]; then
  PLATFORM="linux-x64"
else
  uname_s="$(uname -s)"
  uname_m="$(uname -m)"
  case "${uname_s}/${uname_m}" in
    Darwin/arm64) PLATFORM="macos-arm64" ;;
    Linux/x86_64 | Linux/amd64) PLATFORM="linux-x64" ;;
    MINGW*/x86_64 | MSYS*/x86_64 | CYGWIN*/x86_64) PLATFORM="windows-x64" ;;
    *)
      echo "error: v1 zip smoke is windows-x64, macos-arm64, or linux-x64; got ${uname_s} ${uname_m}" >&2
      exit 1
      ;;
  esac
fi

VERSION="$("$PYTHON" -c "
from pathlib import Path
import re
text = Path('pyproject.toml').read_text(encoding='utf-8')
match = re.search(r'(?m)^version\\s*=\\s*\"([^\"]+)\"', text)
if not match:
    raise SystemExit('error: could not parse version from pyproject.toml')
print(match.group(1))
")"

ZIP_PATH="${1:-${AVO_ENGINE_ZIP:-$ROOT/dist/engine/avo-${VERSION}-${PLATFORM}.zip}}"
if [[ ! -f "$ZIP_PATH" ]]; then
  echo "error: missing engine zip at $ZIP_PATH" >&2
  exit 1
fi

UNPACK="$ROOT/dist/engine/smoke"
rm -rf "$UNPACK"
mkdir -p "$UNPACK"
echo "unpack: $ZIP_PATH -> $UNPACK"
"$PYTHON" -c "
import sys, zipfile
from pathlib import Path
zipfile.ZipFile(sys.argv[1]).extractall(Path(sys.argv[2]))
" "$ZIP_PATH" "$UNPACK"

if [[ -f "$UNPACK/avo/avo.exe" ]]; then
  LAUNCHER="$UNPACK/avo/avo.exe"
elif [[ -f "$UNPACK/avo/avo" ]]; then
  LAUNCHER="$UNPACK/avo/avo"
else
  echo "error: missing onedir launcher under $UNPACK/avo" >&2
  exit 1
fi
chmod +x "$LAUNCHER" 2>/dev/null || true

echo "launcher: $LAUNCHER"
echo "smoke: avo version"
GOT="$("$LAUNCHER" version | tr -d '\r' | head -n 1)"
echo "  $GOT"
if [[ "$GOT" != "$VERSION" ]]; then
  echo "error: avo version '$GOT' != pyproject '$VERSION'" >&2
  exit 1
fi

echo "smoke: avo --help"
"$LAUNCHER" --help >/dev/null
echo "smoke: public verb --help"
for verb in transcribe render shorts cli mcp direction briefstart; do
  echo "smoke: avo $verb --help"
  "$LAUNCHER" "$verb" --help >/dev/null
done
echo "smoke: avo runtime --help"
"$LAUNCHER" runtime --help >/dev/null

# Exercise the actual onedir resource/schema lookup with no provider/media.
echo "smoke: versioned artistic directions (metadata only)"
CATALOG_JSON="$UNPACK/direction-catalog.json"
(
  cd "$UNPACK"
  AVO_ROOT= "$LAUNCHER" direction catalog --json
) >"$CATALOG_JSON"
"$PYTHON" -c "
import json, sys
payload = json.load(open(sys.argv[1], encoding='utf-8'))
assert {item['id'] for item in payload['builtins']} == {
    'analysis-review', 'step-by-step', 'narrative-conversation', 'focused-short'
}, payload
print('direction catalog and bundled schemas ok')
" "$CATALOG_JSON"
BRIEF_PROJECT="$UNPACK/creative-new-video/avo.project.json"
"$PYTHON" -c "
import json, sys
from pathlib import Path
project = Path(sys.argv[1]).resolve()
project.parent.mkdir(parents=True, exist_ok=True)
project.write_text(json.dumps({'provider':'neutral', 'videoId':'engine-smoke', 'rawDir':str(project.parent)}), encoding='utf-8')
" "$BRIEF_PROJECT"
BRIEF_JSON="$UNPACK/briefstart-show.json"
AVO_ROOT= "$LAUNCHER" briefstart show --project "$BRIEF_PROJECT" --json >"$BRIEF_JSON"
"$PYTHON" -c "
import json, sys
from pathlib import Path
assert json.load(open(sys.argv[1], encoding='utf-8'))['status'] == 'bypassed'
assert not (Path(sys.argv[2]).parent / 'edit' / 'briefstart').exists()
print('briefstart raw/no-reference read-only smoke ok')
" "$BRIEF_JSON" "$BRIEF_PROJECT"

FIXTURE="$ROOT/tests/fixtures/engine/stub.wav"
if [[ ! -f "$FIXTURE" ]]; then
  echo "error: missing fixture $FIXTURE" >&2
  exit 1
fi
EDIT="$UNPACK/edit"
mkdir -p "$EDIT"
export AVO_CI_TRANSCRIBE_STUB=1
echo "smoke: avo transcribe (stub must not skip)"
"$LAUNCHER" transcribe "$FIXTURE" --edit-dir "$EDIT"
OUT="$EDIT/transcripts/stub.json"
if [[ ! -s "$OUT" ]]; then
  echo "error: missing transcribe stub output $OUT" >&2
  exit 1
fi
"$PYTHON" -c "
import json, sys
payload = json.loads(open(sys.argv[1], encoding='utf-8').read())
assert payload.get('schema_version') == 1, payload
assert payload.get('language_code') == 'pt-BR', payload
print('transcribe stub json ok')
" "$OUT"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg present; full render/shorts not required for zip smoke"
else
  echo "ffmpeg absent; skipping ffmpeg-full verbs (help already ran)"
fi

echo "done. Zip smoke passed for avo ${VERSION} (${PLATFORM})."
