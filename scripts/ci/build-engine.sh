#!/usr/bin/env bash
# Build the AVO engine onedir zip (PyInstaller) for linux-x64 or macos-arm64.
# Not onefile. Not PyOxidizer. CPU-only CTranslate2 (CUDA stubs stripped in avo.spec).
# Nuitka --mode=standalone is documented fallback only - this script does not run it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

uname_s="$(uname -s)"
uname_m="$(uname -m)"
case "${uname_s}/${uname_m}" in
  Darwin/arm64) PLATFORM="macos-arm64" ;;
  Linux/x86_64 | Linux/amd64) PLATFORM="linux-x64" ;;
  *)
    echo "error: v1 engine zip is linux-x64 or macos-arm64; got ${uname_s} ${uname_m}" >&2
    echo "Intel Mac and other arches are out of scope. Build on the target OS." >&2
    exit 1
    ;;
esac

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "error: python3 not found" >&2
  exit 1
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

echo "building avo ${VERSION} (${PLATFORM}) with PyInstaller onedir"

"$PYTHON" -m pip install -e ".[mcp]" "pyinstaller>=6,<7"

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --workpath "$ROOT/build/engine" \
  --distpath "$ROOT/dist/engine" \
  "$ROOT/packaging/avo.spec"

ONEDIR="$ROOT/dist/engine/avo"
LAUNCHER="$ONEDIR/avo"
if [[ ! -x "$LAUNCHER" ]]; then
  echo "error: missing onedir launcher at $LAUNCHER" >&2
  exit 1
fi

echo "smoke: avo version"
GOT="$("$LAUNCHER" version)"
echo "  $GOT"
if [[ "$GOT" != "$VERSION" ]]; then
  echo "error: avo version '$GOT' != pyproject '$VERSION'" >&2
  exit 1
fi

echo "smoke: avo --help (cold + warm; warm target ≤ 3s)"
"$PYTHON" -c "
import subprocess, sys, time
exe = sys.argv[1]
subprocess.run([exe, '--help'], check=True)
t0 = time.perf_counter()
subprocess.run([exe, '--help'], check=True)
elapsed = time.perf_counter() - t0
print(f'warm --help {elapsed:.2f}s')
if elapsed > 3:
    print('warning: warm onedir --help exceeded 3s NFR; profile hiddenimports before Nuitka', file=sys.stderr)
" "$LAUNCHER"

ZIP_PATH="$ROOT/dist/engine/avo-${VERSION}-${PLATFORM}.zip"
"$PYTHON" -c "
import shutil, sys
from pathlib import Path
dist = Path(sys.argv[1])
base = dist / sys.argv[2]
if Path(str(base) + '.zip').exists():
    Path(str(base) + '.zip').unlink()
shutil.make_archive(str(base), 'zip', root_dir=dist, base_dir='avo')
" "$ROOT/dist/engine" "avo-${VERSION}-${PLATFORM}"

SIZE="$("$PYTHON" -c "from pathlib import Path; print(Path('$ZIP_PATH').stat().st_size)")"
echo "zip: $ZIP_PATH ($SIZE bytes)"
echo "done. Engine zip is AVO Python only (no ffmpeg / HyperFrames / watch-skill / CUDA / weights)."
echo "If a later freeze cannot import faster_whisper, rebuild this same onedir zip with Nuitka --mode=standalone - do not switch to onefile or PyOxidizer."
