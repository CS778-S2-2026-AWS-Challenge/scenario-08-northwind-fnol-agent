param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = "python"
$pythonLauncherArgs = @()

$pythonVersion = & $pythonExecutable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.12") {
    if (-not (Get-Command "py" -ErrorAction SilentlyContinue)) {
        throw "Python 3.12 or newer is required."
    }

    & py -3.12 -c "import sys; assert sys.version_info >= (3, 12)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.12 or newer is required."
    }
    $pythonExecutable = "py"
    $pythonLauncherArgs = @("-3.12")
}

function Invoke-ProjectPython {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$PythonArgs
    )

    & $pythonExecutable @pythonLauncherArgs @PythonArgs
}

Push-Location $repoRoot
try {
    if (-not $SkipInstall) {
        Invoke-ProjectPython -m pip install -r "backend/requirements-dev.txt"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    Invoke-ProjectPython -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Invoke-ProjectPython -m ruff check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Invoke-ProjectPython -m mypy backend tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Invoke-ProjectPython -m pytest --cov=backend --cov-report=term-missing
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    node --test ".github/scripts/pr_policy.test.cjs" ".github/scripts/issue_policy.test.cjs" ".circleci/run-pr-policy.test.cjs"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Push-Location "automation/github-automation"
    try {
        if (-not $SkipInstall) {
            npm ci
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }

        npm run check
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }

    Push-Location "customer"
    try {
        if (-not $SkipInstall) {
            npm ci
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }

        npm run lint
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        npm test
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
