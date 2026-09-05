param(
    [string]$Repo = "",
    [string]$RequiredCheck = "governance-ci",
    [ValidateSet("dev", "main", "all")][string]$Branch = "all"
)

$ErrorActionPreference = "Stop"

if (-not $Repo) {
    $Repo = (gh repo view --json nameWithOwner --jq .nameWithOwner).Trim()
}
if (-not $Repo) {
    throw "Unable to resolve repository. Pass -Repo owner/name."
}

function Invoke-GhJson {
    param(
        [Parameter(Mandatory=$true)][string]$Method,
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)]$Payload
    )
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $result = $json | gh api --method $Method `
        -H "Accept: application/vnd.github+json" `
        -H "X-GitHub-Api-Version: 2022-11-28" `
        $Path --input -
    if ($LASTEXITCODE -ne 0) { throw "GitHub API request failed: $Method $Path" }
    return $result | ConvertFrom-Json
}

function Assert-WorkflowPresent {
    param([Parameter(Mandatory=$true)][string]$TargetBranch)
    gh api "repos/$Repo/contents/.github/workflows/governance-ci.yml?ref=$TargetBranch" --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Refusing to protect ${TargetBranch}: governance-ci workflow is not present on that branch."
    }
}

function New-ProtectionPayload {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$TargetBranch
    )

    return @{
        name = $Name
        target = "branch"
        enforcement = "active"
        bypass_actors = @()
        conditions = @{ ref_name = @{ include = @("refs/heads/$TargetBranch"); exclude = @() } }
        rules = @(
            @{ type = "deletion" },
            @{ type = "non_fast_forward" },
            @{
                type = "pull_request"
                parameters = @{
                    required_approving_review_count = 1
                    dismiss_stale_reviews_on_push = $true
                    required_reviewers = @()
                    require_code_owner_review = $false
                    require_last_push_approval = $false
                    required_review_thread_resolution = $true
                    require_extra_approval_for_unattributed_changes = $false
                    allowed_merge_methods = @("merge", "squash", "rebase")
                }
            },
            @{
                type = "required_status_checks"
                parameters = @{
                    required_status_checks = @( @{ context = $RequiredCheck } )
                    strict_required_status_checks_policy = $true
                    do_not_enforce_on_create = $false
                }
            }
        )
    }
}

function Upsert-Ruleset {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$TargetBranch
    )

    Assert-WorkflowPresent -TargetBranch $TargetBranch
    $rulesets = gh api -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "repos/$Repo/rulesets" | ConvertFrom-Json
    $matches = @($rulesets | Where-Object { $_.name -eq $Name })
    if ($matches.Count -gt 1) { throw "Multiple rulesets named '$Name' exist. Refusing ambiguous update." }
    $payload = New-ProtectionPayload -Name $Name -TargetBranch $TargetBranch
    if ($matches.Count -eq 1) {
        Write-Host "Updating $Name for $TargetBranch..."
        Invoke-GhJson -Method "PUT" -Path "repos/$Repo/rulesets/$($matches[0].id)" -Payload $payload | Out-Null
    } else {
        Write-Host "Creating $Name for $TargetBranch..."
        Invoke-GhJson -Method "POST" -Path "repos/$Repo/rulesets" -Payload $payload | Out-Null
    }
}

gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated." }
$repoInfo = gh api "repos/$Repo" | ConvertFrom-Json
if ($repoInfo.private) { throw "Repository is private. Public-repository ruleset capability is required for the current plan." }
if ($repoInfo.allow_auto_merge) { throw "Repository auto-merge is enabled. Disable it before applying governed protection." }

if ($Branch -eq "all") {
    Assert-WorkflowPresent -TargetBranch "dev"
    Assert-WorkflowPresent -TargetBranch "main"
    Upsert-Ruleset -Name "protect-dev" -TargetBranch "dev"
    Upsert-Ruleset -Name "protect-main" -TargetBranch "main"
} elseif ($Branch -eq "dev") {
    Upsert-Ruleset -Name "protect-dev" -TargetBranch "dev"
} else {
    Upsert-Ruleset -Name "protect-main" -TargetBranch "main"
}

Write-Host "Setting governed required check variable to '$RequiredCheck'..."
gh variable set GOVERNED_REQUIRED_CHECKS --body $RequiredCheck --repo $Repo
if ($LASTEXITCODE -ne 0) { throw "Failed to set GOVERNED_REQUIRED_CHECKS repository variable." }

Write-Host "Requested ruleset phase applied. Do not enable any governed pilot until both branches pass verification."
