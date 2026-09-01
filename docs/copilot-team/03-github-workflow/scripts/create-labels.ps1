param([string]$Repo = "")
$repoArg = @(); if ($Repo) { $repoArg = @('--repo',$Repo) }
$labels = Get-Content "$PSScriptRoot\..\labels.json" | ConvertFrom-Json
foreach ($l in $labels) {
  gh label create $l.name --color $l.color @repoArg 2>$null
  if ($LASTEXITCODE -ne 0) { gh label edit $l.name --color $l.color @repoArg }
}
