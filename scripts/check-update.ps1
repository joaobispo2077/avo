<#
.SYNOPSIS
  AVO - weekly update check (Windows / WSL-from-PowerShell).

.DESCRIPTION
  Lightweight advisory fetch/compare. For full refresh (skills + toolchain +
  provider verify), the user runs /avo.update in their agent.

.EXAMPLE
  pwsh scripts/check-update.ps1 --days 7
#>
$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path
Set-Location $RepoRoot

$Days = 7
$Force = $false
$Yes = $false
$Quiet = $false
$argv = @($args)
for ($i = 0; $i -lt $argv.Count; $i++) {
  switch ($argv[$i]) {
    '--days'  { $Days = [double]$argv[++$i] }
    '--force' { $Force = $true }
    '--yes'   { $Yes = $true }
    '-y'      { $Yes = $true }
    '--quiet' { $Quiet = $true }
    '-h'      { Get-Help $MyInvocation.MyCommand.Path -Detailed; exit 0 }
    '--help'  { Get-Help $MyInvocation.MyCommand.Path -Detailed; exit 0 }
    default   { Write-Host "unknown option: $($argv[$i])" -ForegroundColor Red; exit 1 }
  }
}

function Say([string]$m)  { if (-not $Quiet) { Write-Host $m } }
function Warn([string]$m) { Write-Host "AVO update: $m" -ForegroundColor Yellow }
function Have([string]$n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }

$py = $null
foreach ($c in @('python', 'python3', 'py')) { if (Have $c) { $py = $c; break } }

# --- is a check due? ---------------------------------------------------------
if (-not $Force -and $py) {
  $env:PYTHONPATH = Join-Path $RepoRoot 'src'
  $due = (& $py -m avo.avo_state due --days $Days 2>$null)
  if ($due -and $due -match '^recent') {
    Say "AVO update: checked recently ($($due -replace '^recent ','')); use --force to check now."
    exit 0
  }
}

# --- preflight ---------------------------------------------------------------
if (-not (Have 'git')) { Warn 'git not found; skipping.'; exit 0 }
git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) { Warn 'not a git repo; skipping.'; exit 0 }

# --- dirty tree? -------------------------------------------------------------
$dirty = git status --porcelain 2>$null
if ($dirty) { Warn "working tree has local changes - skipping update (won't clobber). Commit/stash, then rerun."; exit 0 }

# --- fetch (offline => skip) -------------------------------------------------
git fetch --quiet 2>$null
if ($LASTEXITCODE -ne 0) { Warn 'fetch failed (offline?) - skipping. Will retry next session.'; exit 0 }

function Touch-Ts { if ($py) { $env:PYTHONPATH = Join-Path $RepoRoot 'src'; & $py -m avo.avo_state touch-update *> $null } }

$branch = (git rev-parse --abbrev-ref HEAD 2>$null)
git rev-parse --abbrev-ref '@{u}' *> $null
if ($LASTEXITCODE -ne 0) { Warn "no upstream tracking branch for '$branch' - skipping compare."; Touch-Ts; exit 0 }

$behind = [int](git rev-list --count 'HEAD..@{u}' 2>$null)
$ahead = [int](git rev-list --count '@{u}..HEAD' 2>$null)

if ($behind -eq 0) { Say "AVO update: up to date on '$branch'."; Touch-Ts; exit 0 }

Say "AVO update: $behind new commit(s) available on '$branch' (local ahead: $ahead)."
$doPull = $false
if ($Yes) { $doPull = $true }
elseif ([Environment]::UserInteractive) {
  $ans = Read-Host 'Pull latest (fast-forward only)? [y/N]'
  if ($ans -match '^(y|yes)$') { $doPull = $true }
}

if ($doPull) {
  git pull --ff-only --quiet
  if ($LASTEXITCODE -eq 0) { Say "AVO update: pulled latest on '$branch'."; Touch-Ts }
  else { Warn 'fast-forward pull failed (diverged?) - resolve manually. Not clobbering.' }
} else {
  Say "AVO update: skipped pull. Run 'git pull --ff-only' when ready."
  Touch-Ts
}
