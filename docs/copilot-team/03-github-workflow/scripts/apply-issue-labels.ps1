param(
    [string]$Repo = "",
    [int]$StartIssue = 1,
    [int]$EndIssue = 9999,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ============================================================
# Validate GitHub CLI
# ============================================================

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI 'gh' is not available. Install it and run 'gh auth login' first."
}

$repoArg = @()

if ($Repo) {
    $repoArg = @("--repo", $Repo)
}

# ============================================================
# Resolve backlog path
#
# Script:
# docs/copilot-team/03-github-workflow/scripts/
#
# Backlog:
# docs/copilot-team/04-issues/backlog/
# ============================================================

$backlogPath = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..\..\04-issues\backlog")
)

if (-not (Test-Path $backlogPath)) {
    throw "Backlog path does not exist: $backlogPath"
}

$files = Get-ChildItem `
    -Path $backlogPath `
    -Filter "issue-*.md" `
    -File |
    Sort-Object Name

if (-not $files) {
    throw "No backlog issue files found in: $backlogPath"
}

# ============================================================
# Load GitHub issues ONCE
#
# IMPORTANT:
# We include the body because the body contains:
#
#   Issue 001 —
#   Issue 002 —
#
# This lets us match by canonical backlog number rather than
# the malformed GitHub title.
# ============================================================

Write-Host ""
Write-Host "Loading GitHub issues..." -ForegroundColor Cyan

$allIssuesJson = & gh issue list `
    @repoArg `
    --state all `
    --limit 1000 `
    --json number,title,body,labels

if ($LASTEXITCODE -ne 0) {
    throw "Unable to query GitHub issues."
}

$allIssues = $allIssuesJson | ConvertFrom-Json

Write-Host "GitHub issues loaded: $($allIssues.Count)" -ForegroundColor Green

# ============================================================
# Helper: read value after Markdown heading
# ============================================================

function Get-SectionValue {

    param(
        [string[]]$Content,
        [string]$HeadingRegex
    )

    for ($i = 0; $i -lt $Content.Count; $i++) {

        if ($Content[$i] -match $HeadingRegex) {

            for ($j = $i + 1; $j -lt $Content.Count; $j++) {

                $line = $Content[$j].Trim()

                if ($line -match '^##\s+') {
                    break
                }

                if ($line) {
                    return $line
                }
            }
        }
    }

    return $null
}

# ============================================================
# Helper: extract canonical backlog number from GitHub body
#
# Supports:
#
# # Issue 001 —
# Issue 001 —
# Issue 001 -
#
# ============================================================

function Get-BacklogNumberFromBody {

    param(
        [AllowNull()]
        [object]$Body
    )

    if ($null -eq $Body) {
        return $null
    }

    if ($Body -is [System.Array]) {
        $bodyText = $Body -join "`n"
    }
    else {
        $bodyText = [string]$Body
    }

    if ([string]::IsNullOrWhiteSpace($bodyText)) {
        return $null
    }

    $match = [regex]::Match(
        $bodyText,
        '(?im)^\s*#*\s*Issue\s+0*(\d+)'
    )

    if ($match.Success) {
        return [int]$match.Groups[1].Value
    }

    return $null
}

# ============================================================
# Agent mapping
# ============================================================

function Get-AgentLabel {

    param([string]$Agent)

    if (-not $Agent) {
        return $null
    }

    switch -Regex ($Agent) {

        'Architect' {
            return "agent:architect"
        }

        'Backend' {
            return "agent:backend-foundation"
        }

        'Trading Intelligence|AI-Trading' {
            return "agent:trading-intelligence"
        }

        'QA|Security' {
            return "agent:qa-security-review"
        }

        default {
            return $null
        }
    }
}

# ============================================================
# Phase mapping
# ============================================================

function Get-PhaseLabel {

    param([string]$Phase)

    if (-not $Phase) {
        return $null
    }

    switch -Regex ($Phase) {

        '^00' { return "phase:governance" }

        '^01' { return "phase:foundation" }

        '^02' { return "phase:contracts" }

        '^03' { return "phase:data" }

        '^04' { return "phase:analysis" }

        '^05' { return "phase:orchestration" }

        '^06' { return "phase:strategy" }

        '^07' { return "phase:validation" }

        '^08' { return "phase:risk" }

        '^09' { return "phase:approval-execution" }

        '^10' { return "phase:safety" }

        '^11' { return "phase:frontend" }

        '^12' { return "phase:learning" }

        '^13' { return "phase:testing-ops" }

        default {
            return $null
        }
    }
}

# ============================================================
# Optional risk mapping
# ============================================================

function Get-RiskLabel {

    param([string]$Risk)

    if (-not $Risk) {
        return $null
    }

    switch -Regex ($Risk) {

        'blocked.*live|live.*blocked' {
            return "risk:blocked-live-trading"
        }

        'critical|high' {
            return "risk:high"
        }

        'medium' {
            return "risk:medium"
        }

        'low' {
            return "risk:low"
        }

        default {
            return $null
        }
    }
}

# ============================================================
# Optional type mapping
# ============================================================

function Get-TypeLabel {

    param([string]$Type)

    if (-not $Type) {
        return $null
    }

    switch -Regex ($Type) {

        'architecture|adr' {
            return "type:architecture"
        }

        'contract|schema|interface' {
            return "type:contract"
        }

        'backend|foundation|api|infrastructure' {
            return "type:backend"
        }

        'analysis|trading intelligence|strategy|signal|validation' {
            return "type:analysis"
        }

        'test|qa' {
            return "type:test"
        }

        'security|safety' {
            return "type:security"
        }

        'ci|workflow|automation' {
            return "type:ci"
        }

        'frontend|ui|ux' {
            return "type:frontend"
        }

        'learning|adaptive' {
            return "type:learning"
        }

        'doc|documentation' {
            return "type:docs"
        }

        default {
            return $null
        }
    }
}

# ============================================================
# Build GitHub issue lookup by canonical backlog number
# ============================================================

$githubIssueMap = @{}

foreach ($githubIssue in $allIssues) {

    $backlogNumber = Get-BacklogNumberFromBody $githubIssue.body

    if ($null -ne $backlogNumber) {

        if ($githubIssueMap.ContainsKey($backlogNumber)) {

            Write-Warning (
                "Multiple GitHub issues reference backlog Issue " +
                "$backlogNumber. The script will not safely update duplicates."
            )

            $githubIssueMap[$backlogNumber] = $null
        }
        else {

            $githubIssueMap[$backlogNumber] = $githubIssue
        }
    }
}

Write-Host ""
Write-Host "Canonical backlog mappings found: $($githubIssueMap.Count)" -ForegroundColor Green

# ============================================================
# Counters
# ============================================================

$selected = 0
$updated = 0
$skipped = 0
$failed = 0
$titleFixed = 0

# ============================================================
# Process backlog
# ============================================================

foreach ($f in $files) {

    # --------------------------------------------------------
    # Extract backlog issue number from filename
    # --------------------------------------------------------

    if ($f.Name -notmatch '^issue-(\d+)-') {

        Write-Warning "Invalid backlog filename: $($f.Name)"

        $skipped++

        continue
    }

    $catalogIssueNumber = [int]$Matches[1]

    if (
        $catalogIssueNumber -lt $StartIssue -or
        $catalogIssueNumber -gt $EndIssue
    ) {
        continue
    }

    $selected++

    # --------------------------------------------------------
    # Read backlog file
    # --------------------------------------------------------

    $content = Get-Content $f.FullName

    if (-not $content) {

        Write-Warning "Empty backlog file: $($f.Name)"

        $skipped++

        continue
    }

    # --------------------------------------------------------
    # Get canonical correct title
    # --------------------------------------------------------

    $first = $content | Select-Object -First 1

    # Remove only the canonical "# Issue 001" portion first.
# Do not depend on the dash character because the original em-dash
# may have been corrupted during Windows/UTF-8 conversion.

$correctTitle = $first `
    -replace '^#\s*Issue\s+\d+\s*', ''

$correctTitle = $correctTitle.Trim()

# The remaining first token should be the separator:
# —
# -
# ÔÇö
# €”
# or another encoding-corrupted equivalent.
#
# Remove that separator token and retain the actual issue title.

if ($correctTitle -match '^\S+\s+(.+)$') {
    $correctTitle = $Matches[1].Trim()
}

    if (-not $correctTitle) {

        Write-Warning "Unable to determine title: $($f.Name)"

        $skipped++

        continue
    }

    # --------------------------------------------------------
    # Find corresponding GitHub issue using BODY issue number
    # --------------------------------------------------------

    if (-not $githubIssueMap.ContainsKey($catalogIssueNumber)) {

        Write-Warning (
            "GitHub issue not found for canonical backlog " +
            "Issue $catalogIssueNumber"
        )

        $skipped++

        continue
    }

    $githubIssue = $githubIssueMap[$catalogIssueNumber]

    if ($null -eq $githubIssue) {

        Write-Warning (
            "Ambiguous GitHub issue mapping for backlog " +
            "Issue $catalogIssueNumber"
        )

        $skipped++

        continue
    }

    # --------------------------------------------------------
    # Read metadata
    # --------------------------------------------------------

    $agent = Get-SectionValue `
        $content `
        '^##\s+Primary agent'

    $phase = Get-SectionValue `
        $content `
        '^##\s+Phase'

    $risk = Get-SectionValue `
        $content `
        '^##\s+Risk(\s+Level)?'

    $type = Get-SectionValue `
        $content `
        '^##\s+Type'

    # --------------------------------------------------------
    # Determine labels
    # --------------------------------------------------------

    $labels = @()

    $agentLabel = Get-AgentLabel $agent
    $phaseLabel = Get-PhaseLabel $phase
    $riskLabel  = Get-RiskLabel $risk
    $typeLabel  = Get-TypeLabel $type

    if ($agentLabel) {
        $labels += $agentLabel
    }

    if ($phaseLabel) {
        $labels += $phaseLabel
    }

    if ($riskLabel) {
        $labels += $riskLabel
    }

    if ($typeLabel) {
        $labels += $typeLabel
    }

    $labels = @(
        $labels |
        Select-Object -Unique
    )

    # --------------------------------------------------------
    # Display mapping
    # --------------------------------------------------------

    Write-Host ""
    Write-Host (
        "Backlog $catalogIssueNumber -> " +
        "GitHub #$($githubIssue.number)"
    ) -ForegroundColor Cyan

    Write-Host "  Current title : $($githubIssue.title)"
    Write-Host "  Correct title : $correctTitle"
    Write-Host "  Agent         : $agent"
    Write-Host "  Phase         : $phase"

    if ($risk) {
        Write-Host "  Risk          : $risk"
    }

    if ($type) {
        Write-Host "  Type          : $type"
    }

    Write-Host "  Labels        : $($labels -join ', ')"

    # --------------------------------------------------------
    # Determine if title correction is required
    # --------------------------------------------------------

    $needsTitleFix = (
        $githubIssue.title.Trim() -ne
        $correctTitle.Trim()
    )

    if ($needsTitleFix) {
        Write-Host "  TITLE FIX REQUIRED" -ForegroundColor Yellow
    }

    # --------------------------------------------------------
    # Dry run
    # --------------------------------------------------------

    if ($DryRun) {

        Write-Host "  DRY RUN - no update performed." -ForegroundColor Yellow

        continue
    }

    # --------------------------------------------------------
    # Build GitHub edit command
    # --------------------------------------------------------

    try {

        $editArgs = @(
            "issue",
            "edit",
            "$($githubIssue.number)"
        )

        if ($Repo) {
            $editArgs += @(
                "--repo",
                $Repo
            )
        }

        # Fix malformed GitHub issue title
        if ($needsTitleFix) {

            $editArgs += @(
                "--title",
                $correctTitle
            )
        }

        # Add labels
        foreach ($label in $labels) {

            $editArgs += @(
                "--add-label",
                $label
            )
        }

        & gh @editArgs

        if ($LASTEXITCODE -ne 0) {

            throw (
                "gh issue edit failed with exit code " +
                "$LASTEXITCODE"
            )
        }

        if ($needsTitleFix) {
            $titleFixed++
        }

        Write-Host "  UPDATED" -ForegroundColor Green

        $updated++
    }
    catch {

        Write-Host (
            "  FAILED: $($_.Exception.Message)"
        ) -ForegroundColor Red

        $failed++
    }
}

# ============================================================
# Summary
# ============================================================

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Issue Repair / Label Summary" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan

Write-Host "Selected:     $selected"
Write-Host "Updated:      $updated" -ForegroundColor Green
Write-Host "Titles fixed: $titleFixed" -ForegroundColor Yellow
Write-Host "Skipped:      $skipped" -ForegroundColor Yellow
Write-Host "Failed:       $failed" -ForegroundColor Red

if ($DryRun) {

    Write-Host ""
    Write-Host (
        "DRY RUN ONLY - GitHub was not modified."
    ) -ForegroundColor Yellow
}

if ($failed -gt 0) {
    exit 1
}