param(
    [Parameter(Mandatory = $true)]
    [string] $Path,

    [switch] $ReportOwner
)

$ErrorActionPreference = 'Stop'

try {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        exit 2
    }

    $acl = Get-Acl -LiteralPath $item.FullName
    $ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ([string]::IsNullOrWhiteSpace($ownerSid)) {
        exit 3
    }
    if ($ReportOwner) {
        Write-Output $ownerSid
        exit 0
    }

    $allowedSids = @($ownerSid, 'S-1-5-18', 'S-1-5-32-544')
    $rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    foreach ($rule in $rules) {
        if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
            exit 4
        }
        if ($rule.IdentityReference.Value -notin $allowedSids) {
            exit 5
        }
    }

    if (-not ($rules | Where-Object {
        $_.IdentityReference.Value -eq $ownerSid -and
        ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::ReadData)
    })) {
        exit 6
    }
    exit 0
}
catch {
    exit 7
}
