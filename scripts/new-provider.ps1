<#
.SYNOPSIS
  AVO - scaffold a new provider workspace from providers/_template/.

.DESCRIPTION
  Cross-platform PowerShell (Windows / WSL / macOS with pwsh). Stamps
  providers/<name>/ from the template and writes a validated avo.provider.json.
  Missing required values are prompted for when running interactively.

.EXAMPLE
  pwsh scripts/new-provider.ps1 -Name bishop -Kind youtube -RawRoot 'H:\footage\bishop'

.EXAMPLE
  pwsh scripts/new-provider.ps1 bishop
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Name,
  [string]$Kind,
  [string]$RawRoot,
  [string]$Sfx = "",
  [string]$Music = "",
  [string]$Inserts = "",
  [string]$Graphics = "",
  [string]$Lang = "en",
  [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ValidKinds = @('youtube', 'tiktok', 'instagram', 'x', 'podcast', 'shorts', 'generic')

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path
$TemplateDir = Join-Path $RepoRoot (Join-Path 'providers' '_template')

if (-not (Test-Path -LiteralPath $TemplateDir)) {
  throw "template not found: $TemplateDir"
}

$IsInteractive = [Environment]::UserInteractive -and -not $Yes

function Read-OrDefault([string]$Message, [string]$Default = "") {
  if ($script:IsInteractive) {
    $suffix = if ($Default) { " [$Default]" } else { "" }
    $ans = Read-Host "$Message$suffix"
    if ([string]::IsNullOrWhiteSpace($ans)) { return $Default }
    return $ans
  }
  return $Default
}

if ([string]::IsNullOrWhiteSpace($Name)) {
  $Name = Read-OrDefault 'Provider slug (lowercase kebab-case)'
}
if ([string]::IsNullOrWhiteSpace($Name)) { throw 'provider name is required' }
if ($Name -notmatch '^[a-z0-9][a-z0-9-]*$') {
  throw "invalid name '$Name' (use lowercase letters, digits, hyphens)"
}

if ([string]::IsNullOrWhiteSpace($Kind)) {
  $Kind = Read-OrDefault "Kind ($($ValidKinds -join ' '))" 'youtube'
}
if ($ValidKinds -notcontains $Kind) {
  throw "invalid kind '$Kind' (one of: $($ValidKinds -join ', '))"
}

if ([string]::IsNullOrWhiteSpace($RawRoot)) {
  $RawRoot = Read-OrDefault 'External raw footage root (absolute path, NOT inside this repo)'
}
if ([string]::IsNullOrWhiteSpace($RawRoot)) { throw 'raw footage root is required' }

if ([string]::IsNullOrWhiteSpace($Sfx))      { $Sfx = Read-OrDefault 'External SFX library path (optional)' '' }
if ([string]::IsNullOrWhiteSpace($Music))    { $Music = Read-OrDefault 'External music library path (optional)' '' }
if ([string]::IsNullOrWhiteSpace($Inserts))  { $Inserts = Read-OrDefault 'External inserts/b-roll path (optional)' '' }
if ([string]::IsNullOrWhiteSpace($Graphics)) { $Graphics = Read-OrDefault 'External graphics/overlays path (optional)' '' }

$Dest = Join-Path $RepoRoot (Join-Path 'providers' $Name)
if (Test-Path -LiteralPath $Dest) {
  throw "provider already exists: providers/$Name"
}

New-Item -ItemType Directory -Path (Join-Path $Dest 'logo') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Dest 'brand') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $TemplateDir 'DESIGN.md') -Destination (Join-Path $Dest 'DESIGN.md')
Copy-Item -LiteralPath (Join-Path $TemplateDir (Join-Path 'brand' 'palette.json')) -Destination (Join-Path $Dest (Join-Path 'brand' 'palette.json'))
Copy-Item -LiteralPath (Join-Path $TemplateDir (Join-Path 'logo' '.gitkeep')) -Destination (Join-Path $Dest (Join-Path 'logo' '.gitkeep'))

# Build the manifest as an ordered object so ConvertTo-Json escapes values safely.
$manifest = [ordered]@{
  '$schema'     = '../avo.provider.schema.json'
  name          = $Name
  displayName   = $Name
  kind          = $Kind
  description   = ''
  media         = [ordered]@{ rawRoot = $RawRoot }
  assets        = [ordered]@{
    sfx      = $Sfx
    music    = $Music
    inserts  = $Inserts
    graphics = $Graphics
    logos    = "providers/$Name/logo"
  }
  transcription = [ordered]@{ language = $Lang }
  brand         = [ordered]@{
    design  = "providers/$Name/DESIGN.md"
    palette = "providers/$Name/brand/palette.json"
  }
  routingOverrides = [ordered]@{}
}

$json = $manifest | ConvertTo-Json -Depth 8
# Write UTF-8 WITHOUT a BOM (Windows PowerShell 5.1's -Encoding utf8 adds a BOM
# that breaks strict JSON parsers); works on both Windows PowerShell and pwsh 7.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $Dest 'avo.provider.json'), $json, $utf8NoBom)

Write-Output "Created provider workspace: providers/$Name"
Write-Output "  manifest : providers/$Name/avo.provider.json"
Write-Output "  design   : providers/$Name/DESIGN.md"
Write-Output "  logo/    : add SVG source + PNG exports"
Write-Output "  brand/   : edit palette.json"
Write-Output ""
Write-Output "Next: edit DESIGN.md and brand/palette.json; media stays external at:"
Write-Output "  $RawRoot"
