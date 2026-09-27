# Regression for start-dev.ps1's credential boundary (PR #1043 review finding 2: every
# launched child inheriting NORTHWIND_SECRETS_TOKEN because -Environment @{} is an overlay on
# the inherited environment, not a clean slate).
#
# Not wired into CircleCI: this repo has no PowerShell CI lane, only pytest. Run manually
# after touching start-dev.ps1's credential-boundary logic:
#   pwsh -File scripts/test-start-dev-credential-boundary.ps1
#
# Dot-sources start-dev.ps1 only far enough to load Get-CredentialEnvironments (a pure
# function with no network call and no Start-Process), so this never starts a real backend or
# frontend. Then: (1) asserts on the returned hashtables directly, covering the exact gap the
# review found -- a name outside the fixed backend-only list, or a dynamically discovered model
# secret name, must still be null-removed from FrontendEnv; and (2) spawns two minimal real
# child processes with those exact hashtables (the same mechanism Start-Tracked uses) to prove
# -Environment actually behaves as an overlay-with-null-removal in practice, not just in theory.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$failures = [System.Collections.Generic.List[string]]::new()
function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { $failures.Add($Message) }
}

# Load only the function definitions from start-dev.ps1 without running its top-level body
# (which would require a real token and start real processes). AST-filtering the function
# definitions out is the simplest way to reuse the exact same code under test.
$scriptPath = Join-Path $repoRoot 'scripts/start-dev.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$null, [ref]$null)
$functionAsts = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($functionAst in $functionAsts) {
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

# --- Part 1: pure assertions on Get-CredentialEnvironments' output ---

$fakeBundle = "NORTHWIND_MODEL_API_KEY=fake-model-key`nGEMINI_API_KEY=fake-gemini-key`n"
$result = Get-CredentialEnvironments -SecretsToken 'fake-bootstrap-token' -BundleText $fakeBundle

Assert-True ($result.BackendEnv.NORTHWIND_MODEL_API_KEY -eq 'fake-model-key') `
    'BackendEnv did not receive the discovered model key.'
Assert-True ($result.FrontendEnv.ContainsKey('NORTHWIND_MODEL_API_KEY') -and $null -eq $result.FrontendEnv.NORTHWIND_MODEL_API_KEY) `
    'FrontendEnv does not null-remove a dynamically discovered model secret name.'
Assert-True ($result.FrontendEnv.ContainsKey('GEMINI_API_KEY') -and $null -eq $result.FrontendEnv.GEMINI_API_KEY) `
    'FrontendEnv does not null-remove the second dynamically discovered model secret name.'
Assert-True ($result.FrontendEnv.ContainsKey('NORTHWIND_SECRETS_TOKEN') -and $null -eq $result.FrontendEnv.NORTHWIND_SECRETS_TOKEN) `
    'FrontendEnv does not null-remove the bootstrap token.'
Assert-True ($result.FrontendEnv.ContainsKey('NORTHWIND_MONGODB_URI') -and $null -eq $result.FrontendEnv.NORTHWIND_MONGODB_URI) `
    'FrontendEnv does not null-remove NORTHWIND_MONGODB_URI, a name -SkipDocker never touches (the exact gap this test guards).'
Assert-True (-not [string]::IsNullOrEmpty($result.ModelSecretNames))

# A configured credential name absent from *this run's* bundle (a stale value left in the
# developer's shell from an earlier session, or one the endpoint temporarily omitted) must
# still be removed. The fake bundle below deliberately omits GEMINI_API_KEY and
# AWS_BEARER_TOKEN_BEDROCK, both of which config/model-runtime-bindings.json configures.
$partialBundle = "NORTHWIND_MODEL_API_KEY=fake-model-key`n"
$partialResult = Get-CredentialEnvironments -SecretsToken 'fake-bootstrap-token' -BundleText $partialBundle
Assert-True ($partialResult.FrontendEnv.ContainsKey('GEMINI_API_KEY') -and $null -eq $partialResult.FrontendEnv.GEMINI_API_KEY) `
    'FrontendEnv does not null-remove GEMINI_API_KEY when it is absent from the current bundle -- a name config/model-runtime-bindings.json configures but this run never fetched.'
Assert-True ($partialResult.FrontendEnv.ContainsKey('AWS_BEARER_TOKEN_BEDROCK') -and $null -eq $partialResult.FrontendEnv.AWS_BEARER_TOKEN_BEDROCK) `
    'FrontendEnv does not null-remove AWS_BEARER_TOKEN_BEDROCK when it is absent from the current bundle.'

try { Get-CredentialEnvironments -SecretsToken '' -BundleText $fakeBundle; $failures.Add('Missing token did not throw.') }
catch { Assert-True ($_.Exception.Message -match 'NORTHWIND_SECRETS_TOKEN is not set') 'Wrong error for a missing token.' }

try { Get-CredentialEnvironments -SecretsToken 'x' -BundleText ''; $failures.Add('Empty bundle did not throw.') }
catch { Assert-True ($_.Exception.Message -match 'no KEY=VALUE lines') 'Wrong error for an empty bundle.' }

# --- Part 2: prove -Environment behaves as claimed against a real child process ---
#
# Simulates leftover state from an earlier manual-steps run in this same shell (per README):
# a name in the removal set that this process's own environment already carries.
$env:NORTHWIND_MONGODB_URI = 'mongodb://leftover-from-an-earlier-manual-run'

$dumpScript = Join-Path $repoRoot 'scripts/.dev-env-dump-helper.ps1'
Set-Content -Path $dumpScript -Value @'
$watch = @('NORTHWIND_SECRETS_TOKEN','NORTHWIND_MODEL_API_KEY','GEMINI_API_KEY','NORTHWIND_MONGODB_URI')
$present = $watch | Where-Object { Test-Path "env:$_" }
Set-Content -Path $args[0] -Value (($present | Sort-Object) -join ',')
'@
$frontOut = Join-Path $repoRoot 'scripts/.dev-env-dump-frontend.txt'
$backOut = Join-Path $repoRoot 'scripts/.dev-env-dump-backend.txt'
try {
    $env:NORTHWIND_SECRETS_TOKEN = 'fake-bootstrap-token'
    Start-Process pwsh -ArgumentList '-NoProfile', '-File', $dumpScript, $frontOut `
        -Environment $result.FrontendEnv -Wait -WindowStyle Hidden
    Start-Process pwsh -ArgumentList '-NoProfile', '-File', $dumpScript, $backOut `
        -Environment $result.BackendEnv -Wait -WindowStyle Hidden

    $frontendSees = Get-Content $frontOut -ErrorAction SilentlyContinue
    $backendSees = Get-Content $backOut -ErrorAction SilentlyContinue

    Assert-True ([string]::IsNullOrEmpty($frontendSees)) `
        "A real child started with FrontendEnv still saw: $frontendSees"
    Assert-True ($backendSees -match 'NORTHWIND_MODEL_API_KEY' -and $backendSees -match 'GEMINI_API_KEY') `
        "A real child started with BackendEnv did not see the model keys it needs: $backendSees"
    Assert-True ($backendSees -notmatch 'NORTHWIND_SECRETS_TOKEN') `
        "A real child started with BackendEnv still saw the bootstrap token: $backendSees"
}
finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $dumpScript, $frontOut, $backOut
    Remove-Item -ErrorAction SilentlyContinue env:NORTHWIND_MONGODB_URI, env:NORTHWIND_SECRETS_TOKEN
}

# --- Part 3: prove the bootstrap token does not leak to a *direct* child (docker compose,
#     Invoke-Step) that never goes through a Start-Process -Environment overlay at all ---
#
# Runs start-dev.ps1 itself with Invoke-RestMethod faked (offline, no real token) and Docker
# skipped, aborting it deliberately right after the backend starts (a 0s ready timeout), then
# checks this process's own $env: at that point -- exactly what an un-overlaid direct child
# like `docker compose ...` would have inherited had one run after the token fetch.
function Invoke-RestMethod {
    param($Uri, $Headers)
    "NORTHWIND_MODEL_API_KEY=fake-model-key`n"
}
$env:NORTHWIND_SECRETS_TOKEN = 'fake-bootstrap-token-for-direct-child-check'
try {
    . $scriptPath -SkipDocker -BackendOnly -BackendPort 18999 -ReadyTimeoutSeconds 0 3>$null | Out-Null
}
catch {
    # Expected: a 0s ready timeout always throws. What matters here is $env: at this point,
    # not whether the (never-ready) backend came up.
}
finally {
    if (Get-Variable -Name startedProcesses -Scope 0 -ErrorAction SilentlyContinue) {
        foreach ($proc in $startedProcesses) {
            if (-not $proc.HasExited) { & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null }
        }
    }
}
Assert-True (-not (Test-Path env:NORTHWIND_SECRETS_TOKEN)) `
    'NORTHWIND_SECRETS_TOKEN is still set in this process after start-dev.ps1 ran -- any direct external-command child (docker compose, Invoke-Step) started after the fetch would inherit it.'

if ($failures.Count -gt 0) {
    Write-Host 'FAILED:' -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host 'PASSED: frontend children receive none of the backend-only or model-secret names, including ones a -SkipDocker run never touches or that this run''s bundle omitted; the backend receives the model keys it needs and not the bootstrap token; and the bootstrap token is removed from this process''s own environment so a direct, non-overlaid child cannot inherit it either.' -ForegroundColor Green
