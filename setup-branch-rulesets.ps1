# ============================================================
# GitHub Branch Ruleset Setup
# Branches:
#   main = stable/protected
#   dev  = integration/protected
#
# Prerequisites:
#   gh --version
#   gh auth login
#   Run this inside the Git repository
# ============================================================

$ErrorActionPreference = "Stop"

Write-Host "Reading GitHub repository..." -ForegroundColor Cyan

$repo = gh repo view --json nameWithOwner -q ".nameWithOwner"

if (-not $repo) {
    Write-Error "Unable to determine GitHub repository."
    exit 1
}

Write-Host "Repository: $repo" -ForegroundColor Green


# ============================================================
# MAIN RULESET
# ============================================================

$mainRuleset = @{
    name        = "protect-main"
    target      = "branch"
    enforcement = "active"

    conditions = @{
        ref_name = @{
            include = @(
                "refs/heads/main"
            )
            exclude = @()
        }
    }

    rules = @(
        @{
            type = "deletion"
        },

        @{
            type = "non_fast_forward"
        },

        @{
            type = "pull_request"

            parameters = @{
                required_approving_review_count   = 0
                dismiss_stale_reviews_on_push     = $true
                require_code_owner_review         = $false
                require_last_push_approval        = $false
                required_review_thread_resolution = $true

                allowed_merge_methods = @(
                    "merge",
                    "squash",
                    "rebase"
                )
            }
        }
    )

    bypass_actors = @()
}


# ============================================================
# DEV RULESET
# ============================================================

$devRuleset = @{
    name        = "protect-dev"
    target      = "branch"
    enforcement = "active"

    conditions = @{
        ref_name = @{
            include = @(
                "refs/heads/dev"
            )
            exclude = @()
        }
    }

    rules = @(
        @{
            type = "deletion"
        },

        @{
            type = "non_fast_forward"
        },

        @{
            type = "pull_request"

            parameters = @{
                required_approving_review_count   = 0
                dismiss_stale_reviews_on_push     = $true
                require_code_owner_review         = $false
                require_last_push_approval        = $false
                required_review_thread_resolution = $true

                allowed_merge_methods = @(
                    "merge",
                    "squash",
                    "rebase"
                )
            }
        }
    )

    bypass_actors = @()
}


# ============================================================
# Convert to JSON
# ============================================================

$mainJson = $mainRuleset | ConvertTo-Json -Depth 20
$devJson  = $devRuleset  | ConvertTo-Json -Depth 20


$tempDir = Join-Path $env:TEMP "crypto-platform-rulesets"

New-Item `
    -ItemType Directory `
    -Force `
    -Path $tempDir | Out-Null


$mainFile = Join-Path $tempDir "main-ruleset.json"
$devFile  = Join-Path $tempDir "dev-ruleset.json"

$mainJson | Set-Content `
    -Path $mainFile `
    -Encoding UTF8

$devJson | Set-Content `
    -Path $devFile `
    -Encoding UTF8


# ============================================================
# CREATE MAIN RULESET
# ============================================================

Write-Host ""
Write-Host "Creating MAIN branch ruleset..." -ForegroundColor Cyan

gh api `
    --method POST `
    -H "Accept: application/vnd.github+json" `
    -H "X-GitHub-Api-Version: 2022-11-28" `
    "repos/$repo/rulesets" `
    --input $mainFile


# ============================================================
# CREATE DEV RULESET
# ============================================================

Write-Host ""
Write-Host "Creating DEV branch ruleset..." -ForegroundColor Cyan

gh api `
    --method POST `
    -H "Accept: application/vnd.github+json" `
    -H "X-GitHub-Api-Version: 2022-11-28" `
    "repos/$repo/rulesets" `
    --input $devFile


Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "Rulesets created." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

Write-Host ""
Write-Host "MAIN:"
Write-Host "  - Pull request required"
Write-Host "  - Force push blocked"
Write-Host "  - Branch deletion blocked"
Write-Host "  - Review conversations must be resolved"

Write-Host ""
Write-Host "DEV:"
Write-Host "  - Pull request required"
Write-Host "  - Force push blocked"
Write-Host "  - Branch deletion blocked"
Write-Host "  - Review conversations must be resolved"

Write-Host ""
Write-Host "Repository: $repo"