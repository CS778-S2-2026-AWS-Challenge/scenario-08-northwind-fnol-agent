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
# Start-Process -Environment (used to hand model credentials to the backend alone) exists from
# PowerShell 7.3. Windows PowerShell 5.1 would not error on the unknown parameter cleanly
# enough to trust, so refuse up front.
if ($PSVersionTable.PSVersion -lt [version]'7.3') {
    throw "This script needs PowerShell 7.3 or later (found $($PSVersionTable.PSVersion)). Run it with pwsh."
}
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
    # Stopping is left to Stop-StartedProcesses so a late failure tears down everything this
    # invocation started, not only the process that happened to time out.
    throw "$Name did not become ready within $TimeoutSeconds s."
}

# Every process this invocation starts, so a failure at any step can stop all of them rather
# than leaving an already-running backend or frontend hidden on its port.
$startedProcesses = [System.Collections.Generic.List[Diagnostics.Process]]::new()

function Start-Tracked {
    # $Environment adds variables to this one child only; it never touches this shell's
    # environment, so a later child does not inherit what an earlier one was given.
    param([string]$FilePath, [string[]]$ArgumentList, [hashtable]$Environment = @{})
    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -Environment $Environment
    $startedProcesses.Add($process)
    return $process
}

function Stop-StartedProcesses {
    foreach ($process in $startedProcesses) {
        if ($process.HasExited) { continue }
        # npm run dev spawns the real Vite server as a child; /T stops the whole tree so the
        # port is actually released, which Stop-Process on the parent alone would not do.
        & taskkill /PID $process.Id /T /F 2>&1 | Out-Null
    }
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

function Invoke-TrackedStep {
    # Runs one short-lived Python step with an explicit -Environment overlay, so it sees only
    # what it is handed rather than this shell's own $env: (which may carry credentials from an
    # earlier manual run, per the manual steps in README).
    param([string]$Description, [string[]]$ArgumentList, [hashtable]$Environment = @{})
    $process = Start-Process -FilePath 'py' -ArgumentList $ArgumentList `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -Wait -Environment $Environment
    if ($process.ExitCode -ne 0) {
        throw "$Description failed (exit code $($process.ExitCode))."
    }
}

# Credential boundary. Start-Process -Environment is an overlay on the inherited environment,
# not a clean slate: a child sees everything in this shell's $env: plus the overlay, and a
# $null overlay value removes a variable. So nothing secret is ever written to this shell's
# $env:. Backend-only configuration and credentials live in $backendEnv and are passed to the
# backend alone; every other child gets $frontendEnv, an overlay that removes every backend-only
# name, in case the developer's own environment already carries one (an earlier manual-steps
# run in this same shell, for instance).
#
# A fixed name list, independent of which runtime path actually executes below (-SkipDocker
# skips the MongoDB/MinIO names entirely) and independent of which names the current bundle
# fetch happens to return, plus whatever the bundle returns beyond that fixed list, discovered
# dynamically. Building the removal set only from $backendEnv.Keys, or only from the current
# bundle's own key names, both make the same mistake: they only null-remove what this
# particular run happened to set or fetch, so a name a -SkipDocker run never touches, or a
# credential the developer's shell still carries from an earlier session but that dropped out
# of this run's bundle, would reach the frontends. Pure and process-free (no network call, no
# Start-Process) so it can be exercised directly by scripts/test-start-dev-credential-boundary.ps1.
function Get-CredentialEnvironments {
    param([string]$SecretsToken, [string]$BundleText)
    if (-not $SecretsToken) {
        throw ('NORTHWIND_SECRETS_TOKEN is not set. Ask a teammate for the dev secrets token and ' +
            'set it once for your user: [Environment]::SetEnvironmentVariable(' +
            '"NORTHWIND_SECRETS_TOKEN", "<token>", "User"), then open a new terminal.')
    }
    $backendOnlyNames = @(
        'NORTHWIND_SECRETS_TOKEN',
        'NORTHWIND_ENVIRONMENT', 'NORTHWIND_IDENTITY_MODE', 'NORTHWIND_CONTROL_PLANE_DB_PATH',
        'AGENT_RUNTIME_PROFILE', 'DATA_RUNTIME_PROFILE',
        'MODEL_RUNTIME_BINDINGS_PATH', 'MODEL_PROFILE_ID', 'MODEL_TIMEOUT_SECONDS',
        'NORTHWIND_OBJECT_STORAGE_ADAPTER', 'NORTHWIND_OBJECT_STORAGE_ENDPOINT',
        'NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY',
        'NORTHWIND_OBJECT_STORAGE_REGION', 'NORTHWIND_OBJECT_STORAGE_BUCKET', 'NORTHWIND_KNOWLEDGE_BUCKET',
        'NORTHWIND_MONGODB_URI', 'NORTHWIND_MONGODB_DATABASE', 'NORTHWIND_MONGODB_COLLECTION'
    )
    # Every credential_environment_variable name config/model-runtime-bindings.json currently
    # configures, kept in sync manually with that file. Removed from every frontend regardless
    # of whether this run's bundle fetch returned it: a name configured but not returned this
    # time (a stale credential the developer's shell already carries from an earlier session,
    # or one the endpoint temporarily omitted) must be treated the same as one that was.
    $configuredModelCredentialNames = @(
        'NORTHWIND_MODEL_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK', 'GEMINI_API_KEY'
    )
    $backendEnv = @{}
    $frontendEnv = @{}
    foreach ($name in $backendOnlyNames) { $frontendEnv[$name] = $null }
    foreach ($name in $configuredModelCredentialNames) { $frontendEnv[$name] = $null }
    # The backend has no use for the bootstrap token itself, only for the model keys it
    # already unlocked below; null it in case this developer's own environment already has
    # it set (-Environment overlays the inherited environment, it does not replace it).
    $backendEnv.NORTHWIND_SECRETS_TOKEN = $null
    $modelSecretNames = @()
    foreach ($line in ($BundleText -split "`n")) {
        if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $backendEnv[$Matches[1]] = $Matches[2]
            $modelSecretNames += $Matches[1]
            $frontendEnv[$Matches[1]] = $null
        }
    }
    if ($modelSecretNames.Count -eq 0) {
        throw 'The secrets endpoint returned no KEY=VALUE lines; the token may be wrong or revoked.'
    }
    return [PSCustomObject]@{
        BackendEnv       = $backendEnv
        FrontendEnv      = $frontendEnv
        ModelSecretNames = $modelSecretNames
    }
}

# 1. Pull model credentials from the team secrets endpoint. The bundle is KEY=VALUE lines.
#    The bearer token that unlocks the bundle is itself a credential and is never stored in
#    the repository: it comes from the NORTHWIND_SECRETS_TOKEN environment variable, which
#    each developer sets once (see README). It is read into a local, used for one request,
#    and removed from every child this script starts -- no child needs it.
$secretsToken = $env:NORTHWIND_SECRETS_TOKEN
$bundle = if ($secretsToken) {
    Invoke-RestMethod -Uri 'https://ysoseri.us/secret/northwind-dev' `
        -Headers @{ Authorization = "Bearer $secretsToken" }
} else { $null }
# Remove it from this script's own process environment the moment the request is done: every
# later external command in this script -- docker compose, Invoke-Step children, anything not
# started through Start-Tracked's -Environment overlay -- inherits $env: directly, with no
# overlay to null it back out. Leaving it here would leak it to every one of those, not only
# to the Start-Tracked children the overlays cover.
Remove-Item -ErrorAction SilentlyContinue env:NORTHWIND_SECRETS_TOKEN
$credentials = Get-CredentialEnvironments -SecretsToken $secretsToken -BundleText $bundle
$backendEnv = $credentials.BackendEnv
$frontendEnv = $credentials.FrontendEnv
$modelSecretNames = $credentials.ModelSecretNames
$secretsToken = $null

if ($SkipDocker) {
    # Fixture data profile: no MongoDB, no MinIO, no persisted Evidence, no real knowledge
    # retrieval. Only use this when Docker genuinely is not available.
    $backendEnv.DATA_RUNTIME_PROFILE = 'fixture'
    $backendEnv.NORTHWIND_OBJECT_STORAGE_ADAPTER = 'fixture'
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

    # 3. Object-storage settings, shared by knowledge ingestion and the backend. These are the
    #    docker-compose.yml development defaults for the local MinIO, not team secrets, but they
    #    are still backend-only and never reach a frontend.
    $storageEnv = @{
        NORTHWIND_OBJECT_STORAGE_ENDPOINT          = 'http://localhost:9000'
        NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID     = 'minioadmin'
        NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY = 'minioadmin'
        NORTHWIND_OBJECT_STORAGE_REGION            = 'us-east-1'
        NORTHWIND_KNOWLEDGE_BUCKET                 = 'northwind-knowledge'
    }
    foreach ($name in $storageEnv.Keys) { $backendEnv[$name] = $storageEnv[$name] }

    # Ingest the approved knowledge corpus into that MinIO so retrieval is real, not the
    # fixture stub. Run as tracked children with only the storage settings -- explicitly not
    # the model credentials or the bootstrap token, which ingestion has no use for, and which
    # -Environment would otherwise still let this process inherit from this shell's own $env:.
    $ingestionEnv = $storageEnv.Clone()
    $ingestionEnv.NORTHWIND_SECRETS_TOKEN = $null
    foreach ($name in $modelSecretNames) { $ingestionEnv[$name] = $null }
    Invoke-TrackedStep 'knowledge source upload' `
        -ArgumentList @('-3.12', 'scripts/upload_knowledge_sources.py', 'config/knowledge-source-corpus') `
        -Environment $ingestionEnv
    foreach ($request in (Get-ChildItem 'config/knowledge-ingestion-requests/*.json')) {
        Invoke-TrackedStep "knowledge ingestion ($($request.Name))" `
            -ArgumentList @('-3.12', 'scripts/ingest_knowledge_source.py', $request.FullName) `
            -Environment $ingestionEnv
    }

    # 4. Point the backend at that MongoDB and MinIO through the local_mvp persistence profile.
    $backendEnv.DATA_RUNTIME_PROFILE = 'local_mvp'
    $backendEnv.NORTHWIND_OBJECT_STORAGE_ADAPTER = 's3_compatible'
    $backendEnv.NORTHWIND_MONGODB_URI = 'mongodb://localhost:27017/?directConnection=true&replicaSet=rs0'
    $backendEnv.NORTHWIND_MONGODB_DATABASE = 'northwind_fnol'
    $backendEnv.NORTHWIND_MONGODB_COLLECTION = 'northwind_records'
    $backendEnv.NORTHWIND_OBJECT_STORAGE_BUCKET = 'northwind-evidence'
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
$backendEnv.NORTHWIND_ENVIRONMENT = 'development'
$backendEnv.NORTHWIND_IDENTITY_MODE = 'normal'
$backendEnv.NORTHWIND_CONTROL_PLANE_DB_PATH = $controlPlaneDb
$backendEnv.AGENT_RUNTIME_PROFILE = 'model_gateway'
$backendEnv.MODEL_RUNTIME_BINDINGS_PATH = 'config/model-runtime-bindings.json'
$backendEnv.MODEL_PROFILE_ID = 'openrouter-gpt4o-mini'
$backendEnv.MODEL_TIMEOUT_SECONDS = '180'

# 6. Start the backend. The log config prints the structured diagnostic fields the runtime
#    attaches to model-turn events, which is what you want to see while testing a journey.
#    Wait for /health/ready to actually report a non-unavailable status: a hidden process that
#    crashed on startup does not get reported as running.
$backendArguments = @(
    '-3.12', '-m', 'uvicorn', 'backend.main:app',
    '--host', '127.0.0.1', '--port', [string]$BackendPort,
    '--log-config', 'scripts/dev-logging.json'
)

function Start-Frontend {
    param([string]$Prefix, [int]$Port, [string]$BasePath, [int]$TimeoutSeconds, [hashtable]$Environment)
    $process = Start-Tracked -FilePath 'npm.cmd' `
        -ArgumentList @('run', 'dev', '--prefix', $Prefix, '--', '--host', '127.0.0.1', '--port', [string]$Port) `
        -Environment $Environment
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

# Everything from here on starts long-running processes. If any step fails -- including the
# last frontend -- stop every process this invocation started before surfacing the error, so
# a partial run never leaves a hidden backend or Vite server holding its port.
try {
    $backend = Start-Tracked -FilePath 'py' -ArgumentList $backendArguments -Environment $backendEnv
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

    # 7. Start the three frontends and wait for each to actually serve its page. Vite proxies
    #    read the target from these environment variables at startup. These three are the only
    #    names a frontend legitimately needs; everything else in $frontendEnv is a removal.
    $backendOrigin = "http://127.0.0.1:$BackendPort"
    $frontendEnv.VITE_BACKEND_PORT = [string]$BackendPort
    $frontendEnv.WORKBENCH_API_TARGET = $backendOrigin
    $frontendEnv.ADMIN_API_TARGET = $backendOrigin

    $customer = Start-Frontend -Prefix 'customer' -Port $CustomerPort -BasePath '/' -TimeoutSeconds $ReadyTimeoutSeconds -Environment $frontendEnv
    $report.Customer = "$($customer.Url) (ready, PID $($customer.Process.Id))"

    $workbench = Start-Frontend -Prefix 'workbench' -Port $WorkbenchPort -BasePath '/workbench/' -TimeoutSeconds $ReadyTimeoutSeconds -Environment $frontendEnv
    $report.Workbench = "$($workbench.Url) (ready, PID $($workbench.Process.Id))"

    $admin = Start-Frontend -Prefix 'admin' -Port $AdminPort -BasePath '/admin/' -TimeoutSeconds $ReadyTimeoutSeconds -Environment $frontendEnv
    $report.Admin = "$($admin.Url) (ready, PID $($admin.Process.Id))"

    [PSCustomObject]$report
}
catch {
    Stop-StartedProcesses
    throw
}
