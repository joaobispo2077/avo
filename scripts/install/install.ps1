# AVO installer (PowerShell). Delegates to bin/install.cjs (skills + engine zip).
# npx skills add does NOT download the engine zip — this script does.
#
# irm https://raw.githubusercontent.com/joaobispo2077/avo/main/scripts/install/install.ps1 | iex
# pwsh scripts/install/install.ps1 -DryRun -Only cursor

$ErrorActionPreference = 'Stop'
$Repo = if ($env:AVO_INSTALL_REPO) { $env:AVO_INSTALL_REPO } else { 'joaobispo2077/avo' }
$Ref = if ($env:AVO_INSTALL_REF) { $env:AVO_INSTALL_REF } else { 'main' }

function Test-Node {
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error 'AVO: Node.js (≥18) required. Install from https://nodejs.org'
  }
  $major = [int](node -p "process.versions.node.split('.')[0]")
  if ($major -lt 18) {
    Write-Error "AVO: Node $major too old. Need Node ≥18."
  }
}

Test-Node

if ($PSScriptRoot) {
  $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
  $local = Join-Path $repoRoot 'bin\install.cjs'
  if (Test-Path $local) {
    node $local @args
    exit $LASTEXITCODE
  }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) 'avo-install.cjs'
$installUrl = "https://raw.githubusercontent.com/$Repo/$Ref/bin/install.cjs"
Invoke-WebRequest -Uri $installUrl -OutFile $tmp
node $tmp @args
exit $LASTEXITCODE
