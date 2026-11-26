# Daily research check (E2c3): refresh 4h and 1d for the five approved Spot
# pairs through the local web app, verify quality, indicators and the journal
# and strategy-signal reads, and write research-output\daily-check-<date>.md.
# Read/refresh only: it never records a decision or changes other data.
# Exit code 0 = READY, non-zero = PROBLEM (see the report).
param(
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string] $BaseUrl = 'http://127.0.0.1:5173'
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $RepoRoot

$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python virtual environment not found at $python (see docs/research/README.md)."
    exit 2
}

& $python -m trading_platform_api.research daily-check --base-url $BaseUrl --out (Join-Path $RepoRoot 'research-output')
exit $LASTEXITCODE
