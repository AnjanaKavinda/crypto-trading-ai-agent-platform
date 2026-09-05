param(
    [string]$Repo = "",
    [string]$RequiredCheck = "governance-ci"
)

$ErrorActionPreference = "Stop"

if (-not $Repo) {
    $Repo = (gh repo view --json nameWithOwner --jq .nameWithOwner).Trim()
}
if (-not $Repo) {
    throw "Unable to resolve repository. Pass -Repo owner/name."
}

function Assert-True {
    param(
        [Parameter(Mandatory=$true)][bool]$Condition,
        [Parameter(Mandatory=$true)][string]$Message
    )
    if (-not $Condition) { throw $Message }
}

$repoInfo = gh api "repos/$Repo" | ConvertFrom-Json
Assert-True (-not [bool]$repoInfo.allow_auto_merge) "Repository auto-merge must remain disabled."

$rulesets = gh api `
    -H "Accept: application/vnd.github+json" `
    -H "X-GitHub-Api-Version: 2022-11-28" `
    "repos/$Repo/rulesets" | ConvertFrom-Json

foreach ($branch in @("dev", "main")) {
    $name = "protect-$branch"
    $matches = @($rulesets | Where-Object { $_.name -eq $name })
    Assert-True ($matches.Count -eq 1) "Expected exactly one ruleset named '$name'."

    $detail = gh api `
        -H "Accept: application/vnd.github+json" `
        -H "X-GitHub-Api-Version: 2022-11-28" `
        "repos/$Repo/rulesets/$($matches[0].id)" | ConvertFrom-Json

    Assert-True ($detail.enforcement -eq "active") "$name must be active."
    Assert-True ($detail.target -eq "branch") "$name must target branches."
    Assert-True (@($detail.bypass_actors).Count -eq 0) "$name must not have bypass actors."
    Assert-True (@($detail.conditions.ref_name.include) -contains "refs/heads/$branch") "$name must target refs/heads/$branch."
    Assert-True (@($detail.conditions.ref_name.include).Count -eq 1) "$name must target only the governed branch."

    $ruleTypes = @($detail.rules | ForEach-Object { $_.type })
    Assert-True ($ruleTypes -contains "deletion") "$name must block branch deletion."
    Assert-True ($ruleTypes -contains "non_fast_forward") "$name must block force/non-fast-forward pushes."
    Assert-True (-not ($ruleTypes -contains "merge_queue")) "$name must not enable merge queue."

    $prRules = @($detail.rules | Where-Object { $_.type -eq "pull_request" })
    Assert-True ($prRules.Count -eq 1) "$name must contain exactly one pull_request rule."
    $pr = $prRules[0].parameters
    Assert-True ([int]$pr.required_approving_review_count -ge 1) "$name must require at least one approval."
    Assert-True ([bool]$pr.dismiss_stale_reviews_on_push) "$name must dismiss stale approvals."
    Assert-True ([bool]$pr.required_review_thread_resolution) "$name must require review-thread resolution."

    $statusRules = @($detail.rules | Where-Object { $_.type -eq "required_status_checks" })
    Assert-True ($statusRules.Count -eq 1) "$name must contain exactly one required_status_checks rule."
    $status = $statusRules[0].parameters
    Assert-True ([bool]$status.strict_required_status_checks_policy) "$name must use strict required status checks."
    $contexts = @($status.required_status_checks | ForEach-Object { $_.context })
    Assert-True ($contexts -contains $RequiredCheck) "$name must require status check '$RequiredCheck'."

    Write-Host "PASS: $name"
}

Write-Host "PASS: repository auto-merge disabled"
Write-Host "All governed branch-protection invariants verified."
