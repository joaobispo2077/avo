<#
.SYNOPSIS
  AVO - bootstrap a per-video project (avo.project.json) in an external raw dir.

.DESCRIPTION
  Thin wrapper over avo.init_project (shared cross-platform logic).
  All arguments are forwarded to the Python bootstrap.

.EXAMPLE
  pwsh scripts/init-project.ps1 --provider bishop --raw-dir 'H:\footage\vid1'
#>
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path

$py = $env:PYTHON
if ([string]::IsNullOrWhiteSpace($py)) {
  foreach ($cand in @('python3', 'python', 'py')) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $py = $cand; break }
  }
}
if ([string]::IsNullOrWhiteSpace($py)) { throw 'python not found on PATH' }

$env:PYTHONPATH = Join-Path $RepoRoot 'src'
& $py -m avo.init_project @args
exit $LASTEXITCODE
