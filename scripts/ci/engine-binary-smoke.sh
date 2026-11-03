#!/usr/bin/env bash
# Unpack a frozen engine zip and smoke the public CLI. Transcribe stub must not skip.
# Capture operations use the extracted launcher; Python is an archive/JSON harness.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# An explicit native interpreter avoids batch shims in local smoke environments.
# It is used only by the archive/JSON harness, never for engine operations.
if [[ -n "${AVO_SMOKE_PYTHON:-}" ]]; then
  PYTHON="$AVO_SMOKE_PYTHON"
  if [[ ! -f "$PYTHON" ]] || ! "$PYTHON" -c 'from pathlib import Path; import sys; sys.exit(0 if Path(sys.argv[1]).is_absolute() and sys.version_info >= (3, 11) else 1)' "$PYTHON"; then
    echo "error: AVO_SMOKE_PYTHON must name an absolute Python 3.11+ executable" >&2
    exit 1
  fi
elif command -v python3 >/dev/null 2>&1; then
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

VERSION="${VERSION//$'\r'/}"

ZIP_PATH="${1:-${AVO_ENGINE_ZIP:-$ROOT/dist/engine/avo-${VERSION}-${PLATFORM}.zip}}"
if [[ ! -f "$ZIP_PATH" ]]; then
  echo "error: missing engine zip at $ZIP_PATH" >&2
  exit 1
fi

# Every attempt is a fresh OS temp workspace; do not delete computed paths.
SMOKE_NATIVE="$("$PYTHON" -c 'import tempfile; print(tempfile.mkdtemp(prefix="avo-zip-smoke-"))')"
SMOKE_NATIVE="${SMOKE_NATIVE//$'\r'/}"
SMOKE="$SMOKE_NATIVE"
if command -v cygpath >/dev/null 2>&1; then
  SMOKE="$(cygpath -u "$SMOKE_NATIVE")"
fi
UNPACK="$SMOKE/unpacked"
SMOKE_WORK="$SMOKE/work"
mkdir -p "$UNPACK" "$SMOKE_WORK"
echo "unpack: $ZIP_PATH -> $UNPACK"
"$PYTHON" -c "
import os, sys, zipfile
from pathlib import Path
destination = Path(sys.argv[2]).resolve()
with zipfile.ZipFile(sys.argv[1]) as archive:
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if not target.is_relative_to(destination):
            raise SystemExit(f'error: zip entry escapes smoke workspace: {member.filename}')
    archive.extractall(destination)
    if os.name != 'nt':
        for member in archive.infolist():
            mode = (member.external_attr >> 16) & 0o777
            if mode:
                (destination / member.filename).chmod(mode)
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

unset AVO_ROOT PYTHONPATH PYTHONHOME
cd "$SMOKE_WORK"
echo "external smoke workspace: $SMOKE_WORK"

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
cp "$FIXTURE" "$SMOKE_WORK/stub.wav"
FIXTURE="$SMOKE_WORK/stub.wav"
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

# Historical tags may predate capture; a current capture build must expose it.
if "$LAUNCHER" cli animation runtime-install --help >/dev/null 2>&1; then
  if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "error: native capture smoke requires ffmpeg and ffprobe" >&2
    exit 1
  fi
  export PLAYWRIGHT_BROWSERS_PATH="$SMOKE_NATIVE/code-drawn-browsers"
  if [[ -e "$SMOKE/code-drawn-browsers" ]]; then
    echo "error: browser smoke cache must start absent" >&2
    exit 1
  fi
  echo "smoke: bundled driver installs fresh managed Chromium"
  "$LAUNCHER" cli animation runtime-install --engine code-drawn --json >"$SMOKE_WORK/runtime-install.json"
  MOTION="$SMOKE_WORK/canvas"
  "$LAUNCHER" cli animation code-drawn-scaffold --destination "$MOTION" --route canvas --width 128 --height 96 --fps 30/1 --frames 12 --background opaque --background-color '#121212' --json >"$SMOKE_WORK/scaffold.json"
  "$LAUNCHER" cli animation code-drawn-check --composition "$MOTION/composition.json" --output-lock "$MOTION/input-lock.json" --json >"$SMOKE_WORK/check.json"
  "$LAUNCHER" cli animation code-drawn-render --composition "$MOTION/composition.json" --input-lock "$MOTION/input-lock.json" --output "$MOTION/asset.mkv" --json >"$SMOKE_WORK/render.json"
  "$LAUNCHER" cli animation code-drawn-review --candidate "$MOTION/asset.mkv" --source-receipt "$MOTION/asset.generated-asset.json" --output "$MOTION/review" --json >"$SMOKE_WORK/review.json"
  ffprobe -v error -count_frames -show_streams -of json "$MOTION/asset.mkv" >"$SMOKE_WORK/output-probe.json"
  "$PYTHON" - "$SMOKE_WORK" "$SMOKE_NATIVE/code-drawn-browsers" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

work = Path(sys.argv[1]).resolve()
browser_cache = Path(sys.argv[2])
def read(name):
    return json.loads((work / name).read_text(encoding="utf-8"))
def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def content_seal(value, field):
    body = {key: item for key, item in value.items() if key != field}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

for name, operation in (
    ("runtime-install.json", "runtime-install"),
    ("scaffold.json", "code-drawn-scaffold"),
    ("check.json", "code-drawn-check"),
    ("render.json", "code-drawn-render"),
    ("review.json", "code-drawn-review"),
):
    result = read(name)
    assert result["status"] == "ok" and result["operation"] == operation, result
    assert result["selection"]["engine"] == "code-drawn", result
assert read("runtime-install.json")["readiness"]["ready"] is True
assert browser_cache.is_dir() and any(browser_cache.iterdir())
check = read("check.json")
assert any(
    item.get("ready") is True and len(item.get("evidence", {}).get("frames", [])) >= 10
    for item in check["checks"]
), check
manifest = read("canvas/composition.json")
lock = read("canvas/input-lock.json")
receipt = read("canvas/asset.generated-asset.json")
extension = receipt["parameters"]["codeDrawn"]
assert manifest["drawingRoute"] == "canvas"
assert lock["bindingMode"] == "standalone" and "canonicalInputLock" not in lock
assert lock["inputLockHash"] == content_seal(lock, "inputLockHash")
assert extension["inputLockHash"] == lock["inputLockHash"]
assert extension["inputLockRef"]["sha256"] == file_hash(work / "canvas/input-lock.json")
assert lock["manifestRef"]["sha256"] == file_hash(work / "canvas/composition.json")
assert receipt["recordHash"] == content_seal(receipt, "recordHash")
assert receipt["output"]["sha256"] == file_hash(work / "canvas/asset.mkv")
assert receipt["reproducibility"] == "verified" and receipt["approvalReference"] is None
package = read("canvas/review/code-drawn-review.json")
assert package["approval"] is None and package["state"] == "needs-human-judgment"
assert package["candidate"]["sha256"] == receipt["output"]["sha256"]
assert {item["kind"] for item in package["artifacts"]} >= {"frame", "contact-sheet", "small-display"}
verification = extension["outputVerification"]
assert verification["frameCount"] == 12 and verification["silent"] is True
assert verification["codec"] == "ffv1" and verification["pixelFormat"] == "bgra"
assert len(extension["captureEvidence"]["frames"]) >= 10
for identity in ("browserVersion", "browserRevision", "graphics", "driverSha256", "encoderSha256"):
    assert lock["environment"][identity], identity
streams = read("output-probe.json")["streams"]
assert len(streams) == 1 and streams[0]["codec_type"] == "video", streams
video = streams[0]
assert video["codec_name"] == "ffv1" and video["pix_fmt"] == "bgra", video
assert (video["width"], video["height"], int(video["nb_read_frames"])) == (128, 96, 12), video
assert video["r_frame_rate"] == "30/1", video
print("native frozen driver/template/browser/seek/FFV1 receipt smoke passed")
PY
  echo "smoke: provision pinned standalone brush inputs with the native launcher"
  "$LAUNCHER" cli animation runtime-install --engine code-drawn --brush --json >"$SMOKE_WORK/brush-runtime.json"
  for route in svg brush; do
    echo "smoke: native $route starter seek and lossless alpha render"
    MOTION="$SMOKE_WORK/$route"
    "$LAUNCHER" cli animation code-drawn-scaffold --destination "$MOTION" --route "$route" --width 128 --height 96 --fps 30/1 --frames 3 --background transparent --json >"$SMOKE_WORK/$route-scaffold.json"
    "$LAUNCHER" cli animation code-drawn-check --composition "$MOTION/composition.json" --output-lock "$MOTION/input-lock.json" --json >"$SMOKE_WORK/$route-check.json"
    "$LAUNCHER" cli animation code-drawn-render --composition "$MOTION/composition.json" --input-lock "$MOTION/input-lock.json" --output "$MOTION/asset.mkv" --json >"$SMOKE_WORK/$route-render.json"
    ffprobe -v error -count_frames -show_streams -of json "$MOTION/asset.mkv" >"$MOTION/route-output-probe.json"
  done
  "$PYTHON" - "$SMOKE_WORK" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

work = Path(sys.argv[1])
for route in ("svg", "brush"):
    folder = work / route
    manifest = json.loads((folder / "composition.json").read_text(encoding="utf-8"))
    receipt = json.loads((folder / "asset.generated-asset.json").read_text(encoding="utf-8"))
    probe = json.loads((folder / "route-output-probe.json").read_text(encoding="utf-8"))
    assert manifest["drawingRoute"] == route
    assert receipt["output"]["sha256"] == hashlib.sha256((folder / "asset.mkv").read_bytes()).hexdigest()
    assert receipt["approvalReference"] is None
    verification = receipt["parameters"]["codeDrawn"]["outputVerification"]
    assert verification["alphaMode"] == "straight" and verification["rgbaRoundTrip"] == "exact"
    assert verification["frameCount"] == 3 and verification["silent"] is True
    assert len(probe["streams"]) == 1
    video = probe["streams"][0]
    assert video["codec_name"] == "ffv1" and video["pix_fmt"] == "bgra"
    assert int(video["nb_read_frames"]) == 3 and video["r_frame_rate"] == "30/1"
print("native SVG and brush alpha route smokes passed")
PY
elif [[ "${AVO_REQUIRE_CODE_DRAWN_RUNTIME:-0}" == "1" ]]; then
  echo "error: this build requires the native code-drawn command surface" >&2
  exit 1
else
  echo "historical engine: capture unavailable; existing smoke completed"
fi

if "$LAUNCHER" cli costs context --help >/dev/null 2>&1; then
  echo "smoke: bundled cost schemas and no-inference command surface"
  "$LAUNCHER" cli costs capabilities --json >"$SMOKE_WORK/cost-capabilities.json"
  for verb in context observe transition estimate reconcile; do
    "$LAUNCHER" cli costs "$verb" --help >/dev/null
  done
  "$PYTHON" - "$SMOKE_WORK/cost-capabilities.json" <<'PY'
import json
from pathlib import Path
import sys

rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["agents"]
assert len(rows) == 10
assert {row["environment"] for row in rows} >= {"codex-cli", "codex-desktop", "chatgpt", "unknown"}
assert all(row["routes"] and row["limitations"] for row in rows)
print("cost capability and command dispatch smoke passed")
PY
fi

echo "smoke artifacts retained: $SMOKE_NATIVE"

echo "done. Zip smoke passed for avo ${VERSION} (${PLATFORM})."
