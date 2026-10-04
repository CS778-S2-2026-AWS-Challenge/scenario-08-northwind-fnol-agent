$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".demo\northwind-demo.pid"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output "Northwind demo origin is not running."
    return
}

$processId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
if ($processId -notmatch '^\d+$') {
    throw "The demo PID file is invalid: $pidFile"
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Output "Removed a stale demo PID file."
    return
}
if ($process.CommandLine -notlike '*backend.demo:create_demo_app*') {
    throw "PID $processId does not belong to the Northwind demo origin; it was not stopped."
}

Stop-Process -Id $processId
Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
    throw "Northwind demo origin PID $processId did not stop within 10 seconds."
}
Remove-Item -LiteralPath $pidFile -Force
Write-Output "Northwind demo origin stopped."
