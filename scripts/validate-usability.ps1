# Gate 2 — project usability (Windows)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'python3' }
$env:PYTHONPATH = Join-Path $RepoRoot 'src'
& $py -m avo.validate_usability @args
exit $LASTEXITCODE
