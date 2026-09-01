param(
    [string]$Repo = "",
    [int]$StartIssue = 1,
    [int]$EndIssue = 9999,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# Repository argument
# ------------------------------------------------------------

$repoArg = @()

if ($Repo) {
    $repoArg = @("--repo", $Repo)
}

# ------------------------------------------------------------
# Resolve issue backlog path
#
# Script location:
# docs/copilot-team/03-github-workflow/scripts/create-issues.ps1
#
# Backlog location:
# docs/copilot-team/04-issues/backlog/
# ------------------------------------------------------------

$issuesPath = Join-Path `
    $PSScriptRoot `
    "..\..\04-issues\backlog"

$issuesPath = [System.IO.Path]::GetFullPath($issuesPath)

Write-Host ""
Write-Host "GitHub Issue Importer" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backlog path: $issuesPath"
Write-Host "Issue range:  $StartIssue - $EndIssue"

if ($Repo) {
    Write-Host "Repository:   $Repo"
}
else {
    Write-Host "Repository:   Current GitHub repository"
}

Write-Host "Dry run:      $DryRun"
Write-Host ""

# ------------------------------------------------------------
# Validate required tools
# ------------------------------------------------------------

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI 'gh' was not found. Install GitHub CLI and run 'gh auth login' first."
}

# ------------------------------------------------------------
# Validate backlog directory
# ------------------------------------------------------------

if (-not (Test-Path $issuesPath)) {
    throw "Issue backlog directory does not exist: $issuesPath"
}

# ------------------------------------------------------------
# Get issue files
# ------------------------------------------------------------

$files = Get-ChildItem `
    -Path $issuesPath `
    -Filter "issue-*.md" `
    -File |
    Sort-Object Name

if (-not $files) {
    throw "No issue files were found in: $issuesPath"
}

Write-Host "Total backlog files found: $($files.Count)" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------
# Tracking
# ------------------------------------------------------------

$created = 0
$skipped = 0
$failed = 0
$selected = 0

$failures = @()

# ------------------------------------------------------------
# Process issues
# ------------------------------------------------------------

foreach ($f in $files) {

    # Expected filename:
    # issue-001-something.md

    if ($f.Name -notmatch '^issue-(\d+)-') {
        Write-Warning "Skipping invalid issue filename: $($f.Name)"
        $skipped++
        continue
    }

    $issueNumber = [int]$Matches[1]

    # Apply range
    if ($issueNumber -lt $StartIssue -or $issueNumber -gt $EndIssue) {
        continue
    }

    $selected++

    # --------------------------------------------------------
    # Read title
    # --------------------------------------------------------

    $first = Get-Content `
        -Path $f.FullName `
        -TotalCount 1

    if (-not $first) {
        Write-Warning "Skipping empty issue file: $($f.Name)"
        $skipped++
        continue
    }

    # Supports:
    # # Issue 001 — Repository Discovery
    # # Issue 001 - Repository Discovery

    $title = $first `
        -replace '^#\s*Issue\s+\d+\s*[—-]\s*', ''

    $title = $title.Trim()

    if (-not $title) {
        Write-Warning "Unable to determine title from: $($f.Name)"
        $skipped++
        continue
    }

    Write-Host "[$issueNumber] $title" -ForegroundColor Cyan

    # --------------------------------------------------------
    # Dry run
    # --------------------------------------------------------

    if ($DryRun) {
        Write-Host "  Would create from: $($f.FullName)" -ForegroundColor Yellow
        continue
    }

    # --------------------------------------------------------
    # Check whether issue already exists
    # --------------------------------------------------------

    try {

        $existingTitles = gh issue list `
            @repoArg `
            --state all `
            --limit 1000 `
            --json title `
            --jq '.[].title'

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to query existing GitHub issues."
        }

        $alreadyExists = $existingTitles | Where-Object {
            $_.Trim() -eq $title
        }

        if ($alreadyExists) {
            Write-Host "  SKIPPED - issue already exists." -ForegroundColor DarkYellow
            $skipped++
            continue
        }

    }
    catch {
        Write-Warning "Unable to verify duplicate issue: $title"
        Write-Warning $_
    }

    # --------------------------------------------------------
    # Create issue
    # --------------------------------------------------------

    try {

        gh issue create `
            @repoArg `
            --title $title `
            --body-file $f.FullName

        if ($LASTEXITCODE -ne 0) {
            throw "GitHub CLI returned exit code $LASTEXITCODE"
        }

        Write-Host "  CREATED" -ForegroundColor Green
        $created++

    }
    catch {

        Write-Host "  FAILED" -ForegroundColor Red

        $failed++

        $failures += [PSCustomObject]@{
            IssueNumber = $issueNumber
            File        = $f.Name
            Title       = $title
            Error       = $_.Exception.Message
        }
    }

    Write-Host ""
}

# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Issue Import Summary" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

Write-Host "Selected: $selected"
Write-Host "Created:  $created" -ForegroundColor Green
Write-Host "Skipped:  $skipped" -ForegroundColor Yellow
Write-Host "Failed:   $failed" -ForegroundColor Red

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY RUN ONLY - no GitHub issues were created." -ForegroundColor Yellow
}

if ($failures.Count -gt 0) {

    Write-Host ""
    Write-Host "Failures:" -ForegroundColor Red

    $failures | Format-Table `
        IssueNumber, `
        File, `
        Title, `
        Error `
        -AutoSize
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green