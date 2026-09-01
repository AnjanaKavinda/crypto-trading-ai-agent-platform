param(
  [string]$Repo = "",
  [switch]$DryRun
)
$repoArg = @(); if ($Repo) { $repoArg = @('--repo',$Repo) }
$files = Get-ChildItem "$PSScriptRoot\..\issues\issue-*.md" | Sort-Object Name
foreach ($f in $files) {
  $first = Get-Content $f.FullName -TotalCount 1
  $title = $first -replace '^# Issue \d+ — ',' '
  $title = $title.Trim()
  if ($DryRun) { Write-Host "Would create: $title"; continue }
  gh issue create --title $title --body-file $f.FullName @repoArg
  if ($LASTEXITCODE -ne 0) { throw "Failed creating issue from $($f.Name)" }
}
