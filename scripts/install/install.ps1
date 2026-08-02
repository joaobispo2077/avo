# AVO installer (PowerShell). Delegates to bin/install.cjs or npx github:REPO.
#
# irm https://raw.githubusercontent.com/joaobispo2077/avo/main/scripts/install/install.ps1 | iex
# pwsh scripts/install/install.ps1 -DryRun -Only cursor

$ErrorActionPreference = 'Stop'
$Repo = if ($env:AVO_INSTALL_REPO) { $env:AVO_INSTALL_REPO } else { 'joaobispo2077/avo' }

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

$here = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $here '..\..')).Path
if (Test-Path (Join-Path $repoRoot 'bin\install.cjs')) {
  node (Join-Path $repoRoot 'bin\install.cjs') @args
  exit $LASTEXITCODE
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
  Write-Error 'AVO: npx required (ships with Node ≥18).'
}

npx -y "github:$Repo" @args
exit $LASTEXITCODE
