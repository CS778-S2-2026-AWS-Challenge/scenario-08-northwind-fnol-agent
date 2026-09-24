# Start the development backend and claimant frontend against the shared model runtime.
#
# This is the one supported way to run the current claimant journey locally:
#   - model credentials are pulled from the team secrets endpoint on Cloudflare, so nobody
#     keeps private keys in .env or a local vault;
#   - the backend runs the model_gateway runtime profile against the shared
#     config/model-runtime-bindings.json, so everyone talks to the same model. Which model
#     that is (provider, base URL, identifier, capabilities) lives in that file, not here:
#     when a bindings file is loaded, the backend ignores the MODEL_PROVIDER / MODEL_BASE_URL /
#     MODEL_IDENTIFIER / MODEL_SUPPORTS_* environment variables entirely.
#   - the claimant frontend proxies /api to the backend port.
#
# The controlled runtime profile (a deterministic agent that never calls a model) is kept only
# for CI and the test suite. Do not use it for development.
#
# Every step below is also listed as a manual command in README.md if you would rather run
# them one at a time.

param(
    [int]$BackendPort = 8000,
    [int]$CustomerPort = 5173,
    [switch]$BackendOnly,
    [switch]$KeepControlPlane
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot

# 0. Start from a fresh Control Plane so the checked-in model catalogue is what gets published.
#    The backend only seeds the Release Set into an empty Control Plane; an existing database
#    from an earlier checkout keeps its old catalogue (old default model, profiles that have
#    since been removed) and nothing warns you. Claims, sessions and identity live in other
#    databases and are not touched. Pass -KeepControlPlane to preserve operator-published
#    releases you have made locally.
$controlPlaneDb = 'var/dev/control-plane.sqlite3'
New-Item -ItemType Directory -Force -Path (Split-Path $controlPlaneDb) | Out-Null
if (-not $KeepControlPlane) {
    Remove-Item -Force -ErrorAction SilentlyContinue "$controlPlaneDb", "$controlPlaneDb-shm", "$controlPlaneDb-wal"
}

# 1. Pull model credentials from the team secrets endpoint. The bundle is KEY=VALUE lines.
$env:NORTHWIND_SECRETS_TOKEN = 'ysk_nEtbZytRcPqjtTHzaEFD-0Lg2sxlGZ9oUdCfXrfuAJA'
$bundle = Invoke-RestMethod `
    -Uri 'https://ysoseri.us/secret/northwind-dev' `
    -Headers @{ Authorization = "Bearer $($env:NORTHWIND_SECRETS_TOKEN)" }
foreach ($line in ($bundle -split "`n")) {
    if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
        Set-Item -Path "env:$($Matches[1])" -Value $Matches[2]
    }
}

# 2. Select the model_gateway runtime and the shared model profile.
$env:NORTHWIND_ENVIRONMENT = 'development'
$env:NORTHWIND_IDENTITY_MODE = 'normal'
$env:NORTHWIND_CONTROL_PLANE_DB_PATH = $controlPlaneDb
$env:AGENT_RUNTIME_PROFILE = 'model_gateway'
$env:MODEL_RUNTIME_BINDINGS_PATH = 'config/model-runtime-bindings.json'
$env:MODEL_PROFILE_ID = 'openrouter-gpt4o-mini'
$env:MODEL_TIMEOUT_SECONDS = '180'

# 3. Start the backend. The log config prints the structured diagnostic fields the runtime
#    attaches to model-turn events, which is what you want to see while testing a journey.
$backendArguments = @(
    '-3.12', '-m', 'uvicorn', 'backend.main:app',
    '--host', '127.0.0.1', '--port', [string]$BackendPort,
    '--log-config', 'scripts/dev-logging.json'
)
$backend = Start-Process -FilePath 'py' -ArgumentList $backendArguments `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

if ($BackendOnly) {
    [PSCustomObject]@{ Backend = "http://127.0.0.1:$BackendPort (PID $($backend.Id))" }
    return
}

# 4. Start the claimant frontend. customer/vite.config.js proxies /api to VITE_BACKEND_PORT
#    (default 8000).
$env:VITE_BACKEND_PORT = [string]$BackendPort
$customer = Start-Process -FilePath 'npm.cmd' `
    -ArgumentList @('run', 'dev', '--prefix', 'customer', '--', '--host', '127.0.0.1', '--port', [string]$CustomerPort) `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

[PSCustomObject]@{
    Backend  = "http://127.0.0.1:$BackendPort (PID $($backend.Id))"
    Customer = "http://127.0.0.1:$CustomerPort (PID $($customer.Id))"
}
