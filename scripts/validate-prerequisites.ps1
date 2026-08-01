# Gate 1 — orchestrator prerequisites (Windows)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'python3' }
& $py helpers/validate_dependencies.py @args
exit $LASTEXITCODE
