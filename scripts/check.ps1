param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    python -m unittest discover -s tests -p "test_*.py"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Push-Location "customer"
    try {
        if (-not $SkipInstall) {
            npm ci
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }

        npm run lint
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        npm run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}
