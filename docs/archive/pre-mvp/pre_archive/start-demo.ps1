param(
    [switch]$SkipInstall,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repoRoot ".demo"
$pidFile = Join-Path $runtimeDirectory "northwind-demo.pid"
$stdoutLog = Join-Path $runtimeDirectory "northwind-demo.stdout.log"
$stderrLog = Join-Path $runtimeDirectory "northwind-demo.stderr.log"
$healthUrl = "http://127.0.0.1:8765/api/health"

function Get-DemoProcess {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return $null
    }

    $processId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($processId -notmatch '^\d+$') {
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($null -eq $process -or $process.CommandLine -notlike '*backend.demo:create_demo_app*') {
        return $null
    }
    return $process
}

$existingProcess = Get-DemoProcess
if ($null -ne $existingProcess) {
    Write-Output "Northwind demo origin is already running (PID $($existingProcess.ProcessId))."
    Write-Output "Origin: http://127.0.0.1:8765"
    return
}

if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile -Force
}

$pythonExecutable = (& py -3.12 -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Python 3.12 is required."
}

Push-Location $repoRoot
try {
    if (-not $SkipInstall) {
        & $pythonExecutable -m pip install -r "backend/requirements.txt"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        npm ci --prefix customer
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if (-not $SkipBuild) {
        npm run build --prefix customer
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    $arguments = @(
        "-m", "uvicorn",
        "backend.demo:create_demo_app",
        "--factory",
        "--host", "127.0.0.1",
        "--port", "8765",
        "--proxy-headers",
        "--forwarded-allow-ips", "127.0.0.1"
    )
    $previousEnvironment = $env:NORTHWIND_ENVIRONMENT
    $env:NORTHWIND_ENVIRONMENT = "development"
    try {
        $process = Start-Process `
            -FilePath $pythonExecutable `
            -ArgumentList $arguments `
            -WorkingDirectory $repoRoot `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -WindowStyle Hidden `
            -PassThru
    }
    finally {
        $env:NORTHWIND_ENVIRONMENT = $previousEnvironment
    }
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ($process.HasExited) {
            break
        }
        try {
            $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
            # The origin can take a moment to bind after the process starts.
        }
    }

    if (-not $ready) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        $errorTail = Get-Content -LiteralPath $stderrLog -Tail 20 -ErrorAction SilentlyContinue
        throw "Northwind demo origin did not become healthy.`n$errorTail"
    }

    Write-Output "Northwind demo origin started (PID $($process.Id))."
    Write-Output "Origin: http://127.0.0.1:8765"
    Write-Output "Health: $healthUrl"
}
finally {
    Pop-Location
}
