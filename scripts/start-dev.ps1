# Start the complete local system against the shared model runtime: MongoDB, MinIO, ingested
# knowledge, the backend on the local_mvp persistence profile, and all three frontends.
#
# This is the one supported way to run the current claimant journey locally:
#   - model credentials are pulled from the team secrets endpoint on Cloudflare, so nobody
#     keeps private keys in .env or a local vault;
#   - MongoDB and MinIO run through the repo's docker-compose.yml (the same default services
#     used outside the --profile vp container build), so Evidence and claim state persist
#     across restarts instead of living only in the fixture repository;
#   - the approved knowledge corpus is ingested into that MinIO so real local RAG retrieval
#     works, not the fixture knowledge stub;
#   - the backend runs the model_gateway runtime profile against the shared
#     config/model-runtime-bindings.json, so everyone talks to the same model. Which model
#     that is (provider, base URL, identifier, capabilities) lives in that file, not here:
#     when a bindings file is loaded, the backend ignores the MODEL_PROVIDER / MODEL_BASE_URL /
#     MODEL_IDENTIFIER / MODEL_SUPPORTS_* environment variables entirely;
#   - the backend and every frontend are polled until they actually answer before this script
#     reports success. A hidden process that has already crashed does not print as if it were
#     running: each step fails loudly with the process's exit code.
#
# The controlled runtime profile (a deterministic agent that never calls a model) is kept only
# for CI and the test suite. Do not use it for development.
#
# Every step below is also listed as a manual command in README.md if you would rather run
# them one at a time. Pass -SkipDocker to fall back to the fixture data profile (no MongoDB,
# no MinIO, no persisted Evidence, no real knowledge retrieval) when Docker is unavailable.

param(
    [int]$BackendPort = 8000,
    [int]$CustomerPort = 5173,
    [int]$WorkbenchPort = 5174,
    [int]$AdminPort = 5175,
    [switch]$BackendOnly,
    [switch]$KeepControlPlane,
    [switch]$SkipDocker,
    [int]$ReadyTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot

function Wait-Ready {
    # Polls $Probe until it returns $true, or throws if $Process exits first or time runs out.
    # $Probe receives no arguments and must return a boolean; it should catch its own
    # connection errors (the server not accepting connections yet is the expected case, not a
    # failure) and return $false in that case.
    param(
        [Diagnostics.Process]$Process,
        [string]$Name,
        [scriptblock]$Probe,
        [int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "$Name exited (code $($Process.ExitCode)) before becoming ready. Check its output above."
        }
        if (& $Probe) { return }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue }
    throw "$Name did not become ready within $TimeoutSeconds s."
}

function Invoke-Step {
    # Runs an external command and throws with its own exit code on failure, instead of letting
    # a non-zero exit pass silently the way a bare command invocation does under $ErrorActionPreference.
    param([string]$Description, [scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
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

if ($SkipDocker) {
    # Fixture data profile: no MongoDB, no MinIO, no persisted Evidence, no real knowledge
    # retrieval. Only use this when Docker genuinely is not available.
    $env:DATA_RUNTIME_PROFILE = 'fixture'
    $env:NORTHWIND_OBJECT_STORAGE_ADAPTER = 'fixture'
}
else {
    # 2. MongoDB and MinIO through docker-compose.yml, waited to healthy -- not started and
    #    assumed. `--wait` blocks until each service's own healthcheck passes.
    Invoke-Step 'docker compose up mongodb/minio' { docker compose up -d --wait mongodb minio }

    # mongo-init and minio-init are one-shot containers (restart: "no") that depend on the
    # services above already being healthy. Running them here in the foreground turns their
    # actual exit code into a real pass/fail signal instead of a guess.
    Invoke-Step 'mongo-init' { docker compose up --exit-code-from mongo-init mongo-init }
    Invoke-Step 'minio-init' { docker compose up --exit-code-from minio-init minio-init }

    # 3. Ingest the approved knowledge corpus into that MinIO so retrieval is real, not the
    #    fixture stub. This needs only the object-storage credentials, not a model.
    $env:NORTHWIND_OBJECT_STORAGE_ENDPOINT = 'http://localhost:9000'
    $env:NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID = 'minioadmin'
    $env:NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY = 'minioadmin'
    $env:NORTHWIND_OBJECT_STORAGE_REGION = 'us-east-1'
    $env:NORTHWIND_KNOWLEDGE_BUCKET = 'northwind-knowledge'
    Invoke-Step 'knowledge source upload' {
        py -3.12 scripts/upload_knowledge_sources.py config/knowledge-source-corpus
    }
    foreach ($request in (Get-ChildItem 'config/knowledge-ingestion-requests/*.json')) {
        Invoke-Step "knowledge ingestion ($($request.Name))" {
            py -3.12 scripts/ingest_knowledge_source.py $request.FullName
        }
    }

    # 4. Point the backend at that MongoDB and MinIO through the local_mvp persistence profile.
    $env:DATA_RUNTIME_PROFILE = 'local_mvp'
    $env:NORTHWIND_OBJECT_STORAGE_ADAPTER = 's3_compatible'
    $env:NORTHWIND_MONGODB_URI = 'mongodb://localhost:27017/?directConnection=true&replicaSet=rs0'
    $env:NORTHWIND_MONGODB_DATABASE = 'northwind_fnol'
    $env:NORTHWIND_MONGODB_COLLECTION = 'northwind_records'
    $env:NORTHWIND_OBJECT_STORAGE_BUCKET = 'northwind-evidence'
}

# 5. Start from a fresh Control Plane so the checked-in model catalogue is what gets published.
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
$env:NORTHWIND_ENVIRONMENT = 'development'
$env:NORTHWIND_IDENTITY_MODE = 'normal'
$env:NORTHWIND_CONTROL_PLANE_DB_PATH = $controlPlaneDb
$env:AGENT_RUNTIME_PROFILE = 'model_gateway'
$env:MODEL_RUNTIME_BINDINGS_PATH = 'config/model-runtime-bindings.json'
$env:MODEL_PROFILE_ID = 'openrouter-gpt4o-mini'
$env:MODEL_TIMEOUT_SECONDS = '180'

# 6. Start the backend. The log config prints the structured diagnostic fields the runtime
#    attaches to model-turn events, which is what you want to see while testing a journey.
#    Wait for /health/ready to actually report a non-unavailable status: a hidden process that
#    crashed on startup does not get reported as running.
$backendArguments = @(
    '-3.12', '-m', 'uvicorn', 'backend.main:app',
    '--host', '127.0.0.1', '--port', [string]$BackendPort,
    '--log-config', 'scripts/dev-logging.json'
)
$backend = Start-Process -FilePath 'py' -ArgumentList $backendArguments `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
$readyUrl = "http://127.0.0.1:$BackendPort/health/ready"
Wait-Ready -Process $backend -Name 'Backend' -TimeoutSeconds $ReadyTimeoutSeconds -Probe {
    try {
        $result = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 3
        return $result.status -ne 'unavailable'
    }
    catch { return $false }
}

$report = [ordered]@{ Backend = "$readyUrl (ready, PID $($backend.Id))" }

if ($BackendOnly) {
    [PSCustomObject]$report
    return
}

# 7. Start the three frontends and wait for each to actually serve its page. Vite proxies read
#    the target from these environment variables at startup, so they must be set before the
#    process starts.
$env:VITE_BACKEND_PORT = [string]$BackendPort
$backendOrigin = "http://127.0.0.1:$BackendPort"
$env:WORKBENCH_API_TARGET = $backendOrigin
$env:ADMIN_API_TARGET = $backendOrigin

function Start-Frontend {
    param([string]$Prefix, [int]$Port, [string]$BasePath, [int]$TimeoutSeconds)
    $process = Start-Process -FilePath 'npm.cmd' `
        -ArgumentList @('run', 'dev', '--prefix', $Prefix, '--', '--host', '127.0.0.1', '--port', [string]$Port) `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    $url = "http://127.0.0.1:$Port$BasePath"
    Wait-Ready -Process $process -Name $Prefix -TimeoutSeconds $TimeoutSeconds -Probe {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            return $response.StatusCode -eq 200
        }
        catch { return $false }
    }
    return [PSCustomObject]@{ Process = $process; Url = $url }
}

$customer = Start-Frontend -Prefix 'customer' -Port $CustomerPort -BasePath '/' -TimeoutSeconds $ReadyTimeoutSeconds
$report.Customer = "$($customer.Url) (ready, PID $($customer.Process.Id))"

$workbench = Start-Frontend -Prefix 'workbench' -Port $WorkbenchPort -BasePath '/workbench/' -TimeoutSeconds $ReadyTimeoutSeconds
$report.Workbench = "$($workbench.Url) (ready, PID $($workbench.Process.Id))"

$admin = Start-Frontend -Prefix 'admin' -Port $AdminPort -BasePath '/admin/' -TimeoutSeconds $ReadyTimeoutSeconds
$report.Admin = "$($admin.Url) (ready, PID $($admin.Process.Id))"

[PSCustomObject]$report
