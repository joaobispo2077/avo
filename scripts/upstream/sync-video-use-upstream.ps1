# Sync browser-use/video-use reference clone for maintainer diffs (optional).
param(
    [string]$Ref = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Dest = Join-Path $RepoRoot "tools\video-use-upstream"
$Repo = "https://github.com/browser-use/video-use"

if (-not $Ref) {
    $tags = git ls-remote --tags $Repo 2>$null | ForEach-Object {
        if ($_ -match 'refs/tags/(v[0-9][^\^]*$)') { $Matches[1] }
    } | Sort-Object { [version]($_ -replace '^v','') }
    $Ref = if ($tags) { $tags[-1] } else { "main" }
}

Write-Host "upstream ref: $Ref"
Write-Host "destination: $Dest"

if ($DryRun) {
    Write-Host "[dry-run] would sync $Repo @ $Ref -> $Dest"
    exit 0
}

if (Test-Path (Join-Path $Dest ".git")) {
    git -C $Dest fetch --depth 1 origin $Ref 2>$null
    if ($LASTEXITCODE -ne 0) { git -C $Dest fetch origin }
    git -C $Dest checkout -q FETCH_HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { git -C $Dest checkout -q $Ref }
} else {
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    git clone --depth 1 --branch $Ref $Repo $Dest 2>$null
    if ($LASTEXITCODE -ne 0) {
        git clone --depth 1 $Repo $Dest
        git -C $Dest checkout -q $Ref
    }
}

$Sha = git -C $Dest rev-parse HEAD
$Pin = Join-Path $Dest ".avo-upstream-pin.json"
$SyncedAt = (Get-Date).ToUniversalTime().ToString("o")
$PinObj = @{ repo = $Repo; ref = $Ref; sha = $Sha; syncedAt = $SyncedAt }
$PinObj | ConvertTo-Json | Set-Content -Path $Pin -Encoding UTF8
Write-Host "synced $Ref ($Sha)"
