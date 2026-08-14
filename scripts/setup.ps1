<#
.SYNOPSIS
  AVO - AI Video Orchestrator :: setup (Windows / WSL-from-PowerShell).

.DESCRIPTION
  Prepares the toolchain AVO orchestrates. Native primary entrypoint for
  Windows. Idempotent: re-running skips already-satisfied steps. Optional tools
  never fail the run. ai-jail on Windows uses WSL2 (no native sandbox backend).

.PARAMETER Lang
  faster-whisper transcription language (e.g. pt, en, es).
.PARAMETER Model
  Whisper model size to prepare (default: small).
.PARAMETER WithMemory
  Install ai-memory (optional cross-session memory).
.PARAMETER WithJail
  Install ai-jail (optional; verify/install via WSL2 on Windows).
.PARAMETER WithLogo
  Install logo-generator-skill (optional brand assets).
.PARAMETER WithUpstreamRef
  Sync tools/video-use-upstream/ for maintainer diffs (optional).
.PARAMETER Skip
  Skip steps: speckit|engine|watch|hyperframes|remotion (comma-separated).
.PARAMETER Yes
  Non-interactive; accept defaults, no prompts.
.PARAMETER DryRun
  Print actions without executing.

.EXAMPLE
  pwsh scripts/setup.ps1 --lang pt --with-memory
#>

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

# Manual --flag parsing so this matches scripts/setup.sh exactly and the
# `npm run setup -- --lang pt ...` wrapper works identically on every OS.
$Lang = ""
$Model = "small"
$WithMemory = $false
$WithJail = $false
$WithLogo = $false
$WithUpstreamRef = $false
$Skip = @()
$Yes = $false
$DryRun = $false

$argv = @($args)
for ($i = 0; $i -lt $argv.Count; $i++) {
  switch ($argv[$i]) {
    '--lang'        { $Lang = $argv[++$i] }
    '--model'       { $Model = $argv[++$i] }
    '--with-memory' { $WithMemory = $true }
    '--with-jail'   { $WithJail = $true }
    '--with-logo'   { $WithLogo = $true }
    '--with-upstream-ref' { $WithUpstreamRef = $true }
    '--skip'        { $Skip += $argv[++$i] }
    '--yes'         { $Yes = $true }
    '-y'            { $Yes = $true }
    '--dry-run'     { $DryRun = $true }
    '-h'            { Get-Help $MyInvocation.MyCommand.Path -Detailed; exit 0 }
    '--help'        { Get-Help $MyInvocation.MyCommand.Path -Detailed; exit 0 }
    default         { Write-Host "unknown option: $($argv[$i])" -ForegroundColor Red; exit 1 }
  }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path
Set-Location $RepoRoot

$script:Results = New-Object System.Collections.Generic.List[object]
function Record([string]$Tool, [string]$Status, [string]$Note) {
  $script:Results.Add([pscustomobject]@{ Tool = $Tool; Status = $Status; Note = $Note })
}
function Step([string]$Msg) { Write-Host "`n==> $Msg" -ForegroundColor Cyan }
function Info([string]$Msg) { Write-Host "    $Msg" -ForegroundColor DarkGray }
function Have([string]$Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Skipped([string]$Name) { return ($Skip -contains $Name) }

function Run {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Cmd)
  Info ('$ ' + ($Cmd -join ' '))
  if ($DryRun) { return 0 }
  & $Cmd[0] @($Cmd[1..($Cmd.Count - 1)])
  return $LASTEXITCODE
}

function Pick-Python {
  foreach ($c in @('python', 'python3', 'py')) { if (Have $c) { return $c } }
  return $null
}

# ---- 0. Preflight -----------------------------------------------------------
Step 'Preflight'
$IsWsl = Have 'wsl'
Info "OS: Windows  WSL available: $IsWsl  dry-run: $DryRun"
$PY = Pick-Python
if ($PY) { Record 'python' 'OK' ((& $PY --version) 2>&1) } else { Record 'python' 'FAIL' 'not found' }
if (Have 'node') { Record 'node' 'OK' (node --version) } else { Record 'node' 'WARN' 'not found (motion tools need Node >=18)' }
if (Have 'npm')  { Record 'npm' 'OK' (npm --version) } else { Record 'npm' 'WARN' 'not found' }
if (Have 'git')  { Record 'git' 'OK' (git --version) } else { Record 'git' 'WARN' 'not found' }

# ---- language prompt --------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($Lang)) {
  if (-not $Yes -and [Environment]::UserInteractive) {
    $ans = Read-Host 'Transcription language code (faster-whisper, e.g. pt/en/es) [en]'
    $Lang = if ([string]::IsNullOrWhiteSpace($ans)) { 'en' } else { $ans }
  } else { $Lang = 'en' }
}
Info "transcription language: $Lang"

# ---- 1. GitHub Spec Kit -----------------------------------------------------
if (Skipped 'speckit') { Record 'speckit' 'SKIP' '--skip speckit' }
else {
  Step 'GitHub Spec Kit (.specify)'
  if (Test-Path (Join-Path $RepoRoot '.specify')) {
    Record 'speckit' 'OK' 'GitHub Spec Kit present'
  } else {
    Record 'speckit' 'WARN' 'GitHub Spec Kit not detected - run specify init or see https://github.com/github/spec-kit'
  }
}

# ---- 2. video-use engine ----------------------------------------------------
if (Skipped 'engine') { Record 'engine' 'SKIP' '--skip engine' }
else {
  Step 'video-use engine (Python deps + ffmpeg + Whisper model)'
  if (-not $PY) { Record 'engine' 'FAIL' 'python not available' }
  else {
    if (Have 'uv') { Run uv sync | Out-Null } else { Run $PY -m pip install -e . | Out-Null }
    if ((Have 'ffmpeg') -and (Have 'ffprobe')) { Record 'ffmpeg' 'OK' 'on PATH' }
    else {
      Record 'ffmpeg' 'WARN' 'ffmpeg/ffprobe not on PATH (Node ffmpeg-static is a fallback)'
      Info "install: winget install Gyan.FFmpeg  (or) choco install ffmpeg"
    }
    $env:PYTHONPATH = Join-Path $RepoRoot 'src'
    Run $PY -m avo.avo_state init --language $Lang --whisper-model $Model --touch-update | Out-Null
    $rc = Run $PY -m avo.prepare_transcription --model $Model
    if ($rc -eq 0) {
      Record 'engine' 'OK' "deps + model '$Model' (lang $Lang)"
      if ((Run $PY -m avo.models_cli disclosure) -eq 0) { Record 'models' 'OK' 'active models disclosed' }
      else { Record 'models' 'WARN' 'model disclosure skipped' }
    }
    else { Record 'engine' 'WARN' 'deps ok; model prep incomplete (offline?) - rerun python -m avo.prepare_transcription' }
  }
}

# ---- 3. watch-skill ---------------------------------------------------------
if (Skipped 'watch') { Record 'watch' 'SKIP' '--skip watch' }
else {
  Step 'watch-skill (THE LOOP - understand/verify)'
  $ws = Join-Path $RepoRoot 'tools/watch-skill'
  if (Test-Path (Join-Path $ws '.git')) {
    if ((Run git -C $ws pull --ff-only) -eq 0) { Record 'watch' 'OK' "updated $ws" } else { Record 'watch' 'WARN' 'present; update failed (offline?)' }
  } elseif (Have 'git') {
    if ((Run git clone https://github.com/oxbshw/watch-skill $ws) -eq 0) { Record 'watch' 'OK' "cloned to $ws" }
    else { Record 'watch' 'WARN' 'clone failed (offline?) - see https://github.com/oxbshw/watch-skill' }
  } else { Record 'watch' 'WARN' 'git missing - clone watch-skill manually' }
}

# ---- 4. HyperFrames ---------------------------------------------------------
if (Skipped 'hyperframes') { Record 'hyperframes' 'SKIP' '--skip hyperframes' }
else {
  Step 'HyperFrames (default motion engine)'
  if (Have 'npm') {
    if ((Run npm install) -eq 0) {
      if ((Run npx --no-install hyperframes doctor) -eq 0) { Record 'hyperframes' 'OK' 'npm install + doctor' }
      else { Record 'hyperframes' 'WARN' 'installed; hyperframes doctor reported issues' }
    } else { Record 'hyperframes' 'WARN' 'npm install failed (offline?)' }
  } else { Record 'hyperframes' 'WARN' 'npm missing (need Node >=18)' }
}

# ---- 5. Remotion ------------------------------------------------------------
if (Skipped 'remotion') { Record 'remotion' 'SKIP' '--skip remotion' }
else {
  Step 'Remotion (alternate motion engine)'
  Record 'remotion' 'OK' 'installed per-project when needed (see docs/remotion-decision-guide.md)'
}

# ---- 6. ai-memory (optional) ------------------------------------------------
if ($WithMemory) {
  Step 'ai-memory (optional cross-session memory)'
  if (Have 'git') {
    $mem = Join-Path $RepoRoot 'tools/ai-memory'
    if (Test-Path (Join-Path $mem '.git')) {
      if ((Run git -C $mem pull --ff-only) -eq 0) { Record 'ai-memory' 'OK' 'updated' } else { Record 'ai-memory' 'WARN' 'update failed' }
    } elseif ((Run git clone https://github.com/akitaonrails/ai-memory $mem) -eq 0) {
      Record 'ai-memory' 'OK' "cloned to $mem (runs zero-LLM by default)"
    } else { Record 'ai-memory' 'WARN' 'clone failed - see https://github.com/akitaonrails/ai-memory' }
  } else { Record 'ai-memory' 'WARN' 'git missing' }
} else { Record 'ai-memory' 'SKIP' 'enable with --with-memory' }

# ---- 7. ai-jail (optional; Linux/macOS native; WSL2 on Windows) --------------
if ($WithJail) {
  Step 'ai-jail (optional agent sandbox - WSL2 on Windows)'
  if ($IsWsl) {
    Info 'Verifying ai-jail + bubblewrap inside default WSL distro (no native Windows backend).'
    $wslVerify = 'command -v bwrap >/dev/null 2>&1 && command -v ai-jail >/dev/null 2>&1 && ai-jail --version'
    $wslCmd = 'if command -v ai-jail >/dev/null 2>&1; then echo already; elif command -v brew >/dev/null 2>&1; then brew install akitaonrails/tap/ai-jail; elif command -v cargo >/dev/null 2>&1; then cargo install ai-jail; elif command -v mise >/dev/null 2>&1; then mise use -g ai-jail; else echo noinstaller; fi'
    if ($DryRun) { Info "`$ wsl -e bash -lc `"$wslVerify`""; Info "`$ wsl -e bash -lc `"$wslCmd`""; Record 'ai-jail' 'SKIP' 'dry-run (WSL)' }
    else {
      $verifyOut = wsl -e bash -lc $wslVerify 2>&1
      if ($LASTEXITCODE -eq 0) {
        Record 'ai-jail' 'OK' "verified in WSL ($verifyOut)"
      } else {
        $out = wsl -e bash -lc $wslCmd 2>&1
        Info "$out"
        $null = wsl -e bash -lc 'command -v bwrap' 2>&1
        if ($LASTEXITCODE -ne 0) { Record 'bwrap' 'WARN' 'missing in WSL — run: sudo apt install bubblewrap' }
        $verifyOut = wsl -e bash -lc $wslVerify 2>&1
        if ($LASTEXITCODE -eq 0) { Record 'ai-jail' 'OK' 'installed/verified in WSL' }
        elseif ("$out" -match 'noinstaller') { Record 'ai-jail' 'WARN' 'no brew/cargo/mise in WSL - see https://github.com/akitaonrails/ai-jail' }
        else { Record 'ai-jail' 'WARN' "WSL install/verify incomplete ($verifyOut)" }
      }
    }
  } else {
    Record 'ai-jail' 'WARN' 'WSL not available; on Windows use WSL2 (see https://github.com/akitaonrails/ai-jail#windows)'
  }
  Info 'Sandbox tips: mask secrets (e.g. --mask .env); map the EXTERNAL media root read-write.'
  Info 'Operator guide: docs/ai-memory-and-ai-jail.md'
} else { Record 'ai-jail' 'SKIP' 'enable with --with-jail (optional; WSL2 on Windows)' }

# ---- 8. logo-generator-skill (optional) -------------------------------------
if ($WithLogo) {
  Step 'logo-generator-skill (optional brand assets)'
  if (Have 'git') {
    $logo = Join-Path $RepoRoot 'tools/logo-generator-skill'
    if (Test-Path (Join-Path $logo '.git')) {
      if ((Run git -C $logo pull --ff-only) -eq 0) { Record 'logo' 'OK' 'updated' } else { Record 'logo' 'WARN' 'update failed' }
    } elseif ((Run git clone https://github.com/op7418/logo-generator-skill $logo) -eq 0) {
      Record 'logo' 'OK' 'cloned (SVG path keyless; showcase needs GEMINI_API_KEY)'
    } else { Record 'logo' 'WARN' 'clone failed - see https://github.com/op7418/logo-generator-skill' }
  } else { Record 'logo' 'WARN' 'git missing' }
} else { Record 'logo' 'SKIP' 'enable with --with-logo' }

# ---- 9. video-use upstream ref (optional) -----------------------------------
if ($WithUpstreamRef) {
  Step 'video-use upstream reference (maintainer diff)'
  $sync = Join-Path $RepoRoot 'scripts/upstream/sync-video-use-upstream.ps1'
  if ((Run pwsh -File $sync) -eq 0) { Record 'upstream-ref' 'OK' 'tools/video-use-upstream' }
  else { Record 'upstream-ref' 'WARN' 'sync failed — run scripts/upstream/sync-video-use-upstream.ps1' }
} else { Record 'upstream-ref' 'SKIP' 'enable with --with-upstream-ref' }

# ---- Summary ----------------------------------------------------------------
Step 'Setup summary'
$failCount = 0
Write-Host ("    {0,-14} {1,-6} {2}" -f 'TOOL', 'STATUS', 'NOTE')
Write-Host ("    {0,-14} {1,-6} {2}" -f '----', '------', '----')
foreach ($r in $script:Results) {
  switch ($r.Status) {
    'OK'   { $col = 'Green' }
    'WARN' { $col = 'Yellow' }
    'SKIP' { $col = 'DarkGray' }
    'FAIL' { $col = 'Red'; $failCount++ }
    default { $col = 'Gray' }
  }
  Write-Host ("    {0,-14} " -f $r.Tool) -NoNewline
  Write-Host ("{0,-6}" -f $r.Status) -ForegroundColor $col -NoNewline
  Write-Host (" {0}" -f $r.Note)
}

Write-Host ""
if ($failCount -gt 0) {
  Write-Host "Setup finished with $failCount failure(s). Resolve FAIL rows above." -ForegroundColor Red
  exit 1
}
Write-Host "Setup complete. Optional WARN rows are safe to ignore or address later." -ForegroundColor Green
