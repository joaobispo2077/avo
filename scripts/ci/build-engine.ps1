# Build the AVO engine onedir zip (PyInstaller) for windows-x64.
# Not onefile. Not PyOxidizer. CPU-only CTranslate2 (CUDA stubs stripped in avo.spec).
# Nuitka --mode=standalone is documented fallback only - this script does not run it.
$ErrorActionPreference = "Stop"

$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root

$win = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
  [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $win) {
  Write-Error "error: build-engine.ps1 is the windows-x64 packager"
}
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
  Write-Error "error: v1 engine zip on Windows is windows-x64; got $env:PROCESSOR_ARCHITECTURE"
}

$Platform = "windows-x64"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
  $Python = $VenvPython
} else {
  $Python = "python"
}

$Version = & $Python -c @'
from pathlib import Path
import re
text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
if not match:
    raise SystemExit("error: could not parse version from pyproject.toml")
print(match.group(1))
'@
$Version = "$Version".Trim()
if (-not $Version) {
  Write-Error "error: could not read version from pyproject.toml"
}

Write-Host "building avo $Version ($Platform) with PyInstaller onedir"

& $Python -m pip install -e ".[mcp]" "pyinstaller>=6,<7"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --workpath (Join-Path $Root "build\engine") `
  --distpath (Join-Path $Root "dist\engine") `
  (Join-Path $Root "packaging\avo.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Onedir = Join-Path $Root "dist\engine\avo"
$Launcher = Join-Path $Onedir "avo.exe"
if (-not (Test-Path $Launcher)) {
  Write-Error "error: missing onedir launcher at $Launcher"
}

Write-Host "smoke: avo version"
$Got = & $Launcher version
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "  $Got"
if ($Got.Trim() -ne $Version) {
  Write-Error "error: avo version '$Got' != pyproject '$Version'"
}

Write-Host "smoke: avo --help (cold + warm; warm target <= 3s)"
& $Python -c @"
import subprocess, sys, time
exe = sys.argv[1]
subprocess.run([exe, '--help'], check=True)
t0 = time.perf_counter()
subprocess.run([exe, '--help'], check=True)
elapsed = time.perf_counter() - t0
print(f'warm --help {elapsed:.2f}s')
if elapsed > 3:
    print('warning: warm onedir --help exceeded 3s NFR; profile hiddenimports before Nuitka', file=sys.stderr)
"@ $Launcher
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ZipStem = "avo-$Version-$Platform"
& $Python -c @"
import shutil, sys
from pathlib import Path
dist = Path(sys.argv[1])
base = dist / sys.argv[2]
zip_path = Path(str(base) + '.zip')
if zip_path.exists():
    zip_path.unlink()
shutil.make_archive(str(base), 'zip', root_dir=dist, base_dir='avo')
"@ (Join-Path $Root "dist\engine") $ZipStem
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ZipPath = Join-Path $Root "dist\engine\$ZipStem.zip"
$Size = (Get-Item $ZipPath).Length
Write-Host "zip: $ZipPath ($Size bytes)"
Write-Host "done. Engine zip is AVO Python only (no ffmpeg / HyperFrames / watch-skill / CUDA / weights)."
Write-Host "If a later freeze cannot import faster_whisper, rebuild this same onedir zip with Nuitka --mode=standalone - do not switch to onefile or PyOxidizer."
