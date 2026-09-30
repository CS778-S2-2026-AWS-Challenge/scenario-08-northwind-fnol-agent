# Regression for scripts/start-dev.ps1's credential boundary (PR #1088 review: a credential
# name returned by the secrets endpoint but not yet present in
# config/model-runtime-bindings.json -- a new provider being trialled, for instance -- must
# still be removed from every frontend, not only names the Python side already knows about).
#
# Not wired into CircleCI: this repo has no PowerShell CI lane, only pytest. Run manually
# after touching scripts/start-dev.ps1's credential-boundary logic:
#   pwsh -File scripts/test-start-dev-credential-boundary.ps1
#
# Loads only Split-CredentialEnvironments (a pure, process-free function) via AST extraction,
# so this never starts a real backend, frontend, or network call. Then: (1) asserts on its
# output directly, including the exact gap this test guards -- a name present in
# credentials.secrets but absent from both the fixed backend-only list and
# configured_credential_names; and (2) spawns two minimal real child processes with the
# resulting BackendEnv/FrontendEnv (the same mechanism Start-Tracked uses) to prove
# -Environment actually enforces that removal in practice, not just in the returned hashtable.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$failures = [System.Collections.Generic.List[string]]::new()
function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { $failures.Add($Message) }
}

$scriptPath = Join-Path $repoRoot 'scripts/start-dev.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$null, [ref]$null)
$functionAst = $ast.FindAll(
    { param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Split-CredentialEnvironments' },
    $false
) | Select-Object -First 1
if (-not $functionAst) { throw 'Split-CredentialEnvironments was not found in scripts/start-dev.ps1.' }
. ([scriptblock]::Create($functionAst.Extent.Text))

# --- Part 1: pure assertions on Split-CredentialEnvironments' output ---

# NEW_PROVIDER_API_KEY simulates the exact gap the review found: the endpoint already returns
# it, but config/model-runtime-bindings.json does not configure it yet (a new provider being
# trialled before its binding entry lands). NORTHWIND_MODEL_API_KEY is a name the bindings file
# already configures, to prove both sources are still covered together.
$credentials = [PSCustomObject]@{
    secrets                     = [PSCustomObject]@{
        NORTHWIND_MODEL_API_KEY = 'fake-model-key'
        NEW_PROVIDER_API_KEY    = 'fake-new-provider-key'
    }
    configured_credential_names = @('NORTHWIND_MODEL_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK', 'GEMINI_API_KEY')
}
$result = Split-CredentialEnvironments -Credentials $credentials

Assert-True ($result.BackendEnv.NORTHWIND_MODEL_API_KEY -eq 'fake-model-key') `
    'BackendEnv did not receive a preconfigured model key.'
Assert-True ($result.BackendEnv.NEW_PROVIDER_API_KEY -eq 'fake-new-provider-key') `
    'BackendEnv did not receive a dynamically returned, not-preconfigured model key.'
Assert-True ($result.FrontendEnv.ContainsKey('NEW_PROVIDER_API_KEY') -and $null -eq $result.FrontendEnv.NEW_PROVIDER_API_KEY) `
    'FrontendEnv does not null-remove a credential name the endpoint returned but config/model-runtime-bindings.json does not yet configure -- the exact regression this test guards.'
Assert-True ($result.FrontendEnv.ContainsKey('NORTHWIND_MODEL_API_KEY') -and $null -eq $result.FrontendEnv.NORTHWIND_MODEL_API_KEY) `
    'FrontendEnv does not null-remove a preconfigured model key.'
Assert-True ($result.FrontendEnv.ContainsKey('AWS_BEARER_TOKEN_BEDROCK') -and $null -eq $result.FrontendEnv.AWS_BEARER_TOKEN_BEDROCK) `
    'FrontendEnv does not null-remove a configured credential name absent from this run''s bundle.'
Assert-True ($result.FrontendEnv.ContainsKey('NORTHWIND_MONGODB_URI') -and $null -eq $result.FrontendEnv.NORTHWIND_MONGODB_URI) `
    'FrontendEnv does not null-remove NORTHWIND_MONGODB_URI from the fixed backend-only name list.'
Assert-True ($result.FrontendEnv.ContainsKey('NORTHWIND_SECRETS_TOKEN') -and $null -eq $result.FrontendEnv.NORTHWIND_SECRETS_TOKEN) `
    'FrontendEnv does not null-remove the bootstrap token.'
Assert-True ($result.BackendEnv.ContainsKey('NORTHWIND_SECRETS_TOKEN') -and $null -eq $result.BackendEnv.NORTHWIND_SECRETS_TOKEN) `
    'BackendEnv does not null-remove the bootstrap token (the backend has no use for it either).'
Assert-True (($result.ModelSecretNames | Sort-Object) -join ',' -eq 'NEW_PROVIDER_API_KEY,NORTHWIND_MODEL_API_KEY') `
    'ModelSecretNames does not exactly match the names the fake bundle returned.'

# --- Part 2: prove -Environment enforces that removal against a real child process ---
#
# Simulates leftover state from an earlier manual-steps run in this same shell (per README):
# names in the removal set that this process's own environment already carries.
$env:NORTHWIND_MONGODB_URI = 'mongodb://leftover-from-an-earlier-manual-run'
$env:NEW_PROVIDER_API_KEY = 'leftover-new-provider-key-from-an-earlier-manual-run'

$dumpScript = Join-Path $repoRoot 'scripts/.dev-env-dump-helper.ps1'
Set-Content -Path $dumpScript -Value @'
$watch = @('NORTHWIND_SECRETS_TOKEN','NORTHWIND_MODEL_API_KEY','NEW_PROVIDER_API_KEY','NORTHWIND_MONGODB_URI')
$present = $watch | Where-Object { Test-Path "env:$_" }
Set-Content -Path $args[0] -Value (($present | Sort-Object) -join ',')
'@
$frontOut = Join-Path $repoRoot 'scripts/.dev-env-dump-frontend.txt'
$backOut = Join-Path $repoRoot 'scripts/.dev-env-dump-backend.txt'
try {
    Start-Process pwsh -ArgumentList '-NoProfile', '-File', $dumpScript, $frontOut `
        -Environment $result.FrontendEnv -Wait -WindowStyle Hidden
    Start-Process pwsh -ArgumentList '-NoProfile', '-File', $dumpScript, $backOut `
        -Environment $result.BackendEnv -Wait -WindowStyle Hidden

    $frontendSees = Get-Content $frontOut -ErrorAction SilentlyContinue
    $backendSees = Get-Content $backOut -ErrorAction SilentlyContinue

    Assert-True ([string]::IsNullOrEmpty($frontendSees)) `
        "A real frontend child still saw: $frontendSees -- including the dynamically returned, not-preconfigured name if it appears above."
    Assert-True ($backendSees -match 'NORTHWIND_MODEL_API_KEY' -and $backendSees -match 'NEW_PROVIDER_API_KEY') `
        "A real backend child did not see the model keys it needs: $backendSees"
    Assert-True ($backendSees -notmatch 'NORTHWIND_SECRETS_TOKEN') `
        "A real backend child still saw the bootstrap token: $backendSees"
}
finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $dumpScript, $frontOut, $backOut
    Remove-Item -ErrorAction SilentlyContinue env:NORTHWIND_MONGODB_URI, env:NEW_PROVIDER_API_KEY
}

if ($failures.Count -gt 0) {
    Write-Host 'FAILED:' -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host 'PASSED: a real frontend child receives none of the backend-only, preconfigured-credential, or dynamically-returned-but-not-yet-configured secret names; a real backend child receives the model keys it needs and not the bootstrap token.' -ForegroundColor Green
