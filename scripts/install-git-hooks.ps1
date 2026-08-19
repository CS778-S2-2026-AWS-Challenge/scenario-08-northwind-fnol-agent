$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

& git -C $repoRoot config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure the repository Git hooks path."
}

$configuredPath = & git -C $repoRoot config --get core.hooksPath
if ($LASTEXITCODE -ne 0 -or $configuredPath -ne ".githooks") {
    throw "The repository Git hooks path was not configured as expected."
}

Write-Host "Git hooks enabled from .githooks. The pre-push hook runs scripts/check.ps1."
