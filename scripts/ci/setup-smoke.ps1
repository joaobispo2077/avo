# Maintainer smoke: full setup contract on Windows CI
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 --yes --lang en --skip remotion
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validate-prerequisites.ps1 --include-optional
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validate-usability.ps1
