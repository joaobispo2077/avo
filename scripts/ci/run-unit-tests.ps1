# Canonical unit test entry for Windows. Requires: pip install -e ".[dev]"
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root
if ($args.Count -eq 0) {
  pytest -m "not project" @args
} else {
  pytest @args
}
exit $LASTEXITCODE
