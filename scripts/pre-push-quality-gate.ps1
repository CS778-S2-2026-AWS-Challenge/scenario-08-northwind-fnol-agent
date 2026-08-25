[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$modeValue = if ($null -eq $env:NORTHWIND_QUALITY_GATE_MODE) { "auto" } else { $env:NORTHWIND_QUALITY_GATE_MODE }
$providerValue = if ($null -eq $env:NORTHWIND_REMOTE_CI_PROVIDER) { "none" } else { $env:NORTHWIND_REMOTE_CI_PROVIDER }
$mode = $modeValue.ToLowerInvariant()
$provider = $providerValue.ToLowerInvariant()

if ($mode -notin @("auto", "local", "off")) {
    throw "NORTHWIND_QUALITY_GATE_MODE must be auto, local, or off."
}

if ($provider -notin @("none", "github", "circleci")) {
    throw "NORTHWIND_REMOTE_CI_PROVIDER must be none, github, or circleci."
}

function Test-GitHubActionsEnabled {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        return $false
    }

    $remote = & git config --get remote.origin.url
    if ($LASTEXITCODE -ne 0 -or -not $remote) {
        return $false
    }

    $repository = $remote.Trim() -replace '^https://github\.com/', '' -replace '^git@github\.com:', ''
    $repository = $repository -replace '\.git$', ''
    if ($repository -notmatch '^[^/]+/[^/]+$') {
        return $false
    }

    $enabled = & gh api "repos/$repository/actions/permissions" --jq '.enabled' 2>$null
    return $LASTEXITCODE -eq 0 -and $enabled.Trim() -eq "true"
}

function Test-RemoteQualityGate {
    if ($provider -eq "circleci") {
        return $true
    }

    if ($provider -eq "github" -or $provider -eq "none") {
        return Test-GitHubActionsEnabled
    }

    return $false
}

if ($mode -eq "off") {
    Write-Warning "Local quality gate skipped by NORTHWIND_QUALITY_GATE_MODE=off. Use only for authorised maintenance operations."
    exit 0
}

if ($mode -eq "auto" -and (Test-RemoteQualityGate)) {
    $activeProvider = if ($provider -eq "none") { "GitHub Actions" } else { $provider }
    Write-Host "Remote quality gate detected ($activeProvider); skipping the additional local pre-push gate."
    exit 0
}

Write-Host "Remote quality gate is unavailable; running the local quality gate."
$checkScript = Join-Path $PSScriptRoot "check.ps1"
$checkArguments = @()
if ($SkipInstall) {
    $checkArguments += "-SkipInstall"
}

& $checkScript @checkArguments
exit $LASTEXITCODE
