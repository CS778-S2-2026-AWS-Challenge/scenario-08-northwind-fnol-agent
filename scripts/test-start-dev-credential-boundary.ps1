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

if ($failures.Count -gt 0) {
    Write-Host 'FAILED:' -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host 'PASSED: frontend children receive none of the backend-only or model-secret names (including ones a -SkipDocker run never touches); the backend receives the model keys it needs and not the bootstrap token.' -ForegroundColor Green
