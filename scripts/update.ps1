<#
.SYNOPSIS
  AVO self-update: git pull (ff-only) + full skills/toolchain refresh.

.DESCRIPTION
  Preserves gitignored provider workspaces under providers/<slug>/.

.EXAMPLE
  pwsh scripts/update.ps1 apply --yes
  pwsh scripts/update.ps1 check
#>
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path
Set-Location $RepoRoot

$py = $null
foreach ($c in @('python', 'python3', 'py')) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) { Write-Error 'AVO update: python not found'; exit 1 }

$cmd = 'apply'
$forward = @()
if ($args.Count -gt 0 -and ($args[0] -eq 'check' -or $args[0] -eq 'apply')) {
  $cmd = $args[0]
  $forward = $args[1..($args.Count - 1)]
} else {
  $forward = $args
}

$env:PYTHONPATH = Join-Path $RepoRoot 'src'
& $py -m avo.update $cmd @forward
exit $LASTEXITCODE
