param(
    [string]$Repo = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI 'gh' is not available. Install it and run 'gh auth login' first."
}

$repoArg = @()
if ($Repo) { $repoArg = @("--repo", $Repo) }

$labelsPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\labels.json"))
if (-not (Test-Path $labelsPath)) { throw "labels.json not found: $labelsPath" }

$labels = Get-Content $labelsPath -Raw | ConvertFrom-Json

$created = 0
$updated = 0
$failed = 0

foreach ($l in $labels) {
    $name = [string]$l.name
    $color = ([string]$l.color).TrimStart("#")
    $description = [string]$l.description

    & gh label create $name --color $color --description $description @repoArg 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "CREATED  $name" -ForegroundColor Green
        $created++
        continue
    }

    & gh label edit $name --color $color --description $description @repoArg
    if ($LASTEXITCODE -eq 0) {
        Write-Host "UPDATED  $name" -ForegroundColor Yellow
        $updated++
    } else {
        Write-Host "FAILED   $name" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "Created: $created"
Write-Host "Updated: $updated"
Write-Host "Failed:  $failed"

if ($failed -gt 0) { exit 1 }
