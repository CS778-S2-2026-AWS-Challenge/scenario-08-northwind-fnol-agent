$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "stop-demo.ps1")
& (Join-Path $PSScriptRoot "start-demo.ps1") -SkipInstall -SkipBuild

Write-Output "The in-memory demonstration fixture has been reset."
