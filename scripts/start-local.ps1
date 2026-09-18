param(
    [int]$BackendPort = 8000,
    [int]$CustomerPort = 5173,
    [int]$WorkbenchPort = 5174,
    [int]$AdminPort = 5175
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$bindingPath = Join-Path $repoRoot 'config\model-runtime-bindings.json'
$envPath = Join-Path $repoRoot '.env'
Import-Module (Join-Path $PSScriptRoot 'Northwind.LocalSecrets.psm1') -Force

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $escapedName = [Regex]::Escape($Name)
    $resolvedValue = $null
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -notmatch "^\s*$escapedName\s*=\s*(.*)$") { continue }
        $value = $Matches[1].Trim()
        if (
            $value.Length -ge 2 -and
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            $value.Length -ge 2 -and
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $resolvedValue = $value
    }
    return $resolvedValue
}

$bindingVariable = 'MODEL_RUNTIME_BINDINGS_PATH'
$previousBindingPath = [Environment]::GetEnvironmentVariable(
    $bindingVariable,
    [EnvironmentVariableTarget]::Process
)
$qwenEndpointVariable = 'NORTHWIND_QWEN_BASE_URL'
$previousQwenEndpoint = [Environment]::GetEnvironmentVariable(
    $qwenEndpointVariable,
    [EnvironmentVariableTarget]::Process
)
$qwenEndpoint = $previousQwenEndpoint
if ([string]::IsNullOrWhiteSpace($qwenEndpoint)) {
    $qwenEndpoint = Get-DotEnvValue -Path $envPath -Name $qwenEndpointVariable
}
if ([string]::IsNullOrWhiteSpace($qwenEndpoint)) {
    $qwenEndpoint = [Environment]::GetEnvironmentVariable(
        'MODEL_BASE_URL',
        [EnvironmentVariableTarget]::Process
    )
}
if ([string]::IsNullOrWhiteSpace($qwenEndpoint)) {
    $qwenEndpoint = Get-DotEnvValue -Path $envPath -Name 'MODEL_BASE_URL'
}

$credentialNames = @(
    Get-Content -Raw -LiteralPath $bindingPath |
        ConvertFrom-Json |
        Where-Object {
            -not $_.PSObject.Properties['evaluation_status'] -or
            $_.evaluation_status -ne 'unavailable'
        } |
        ForEach-Object { $_.credential_environment_variable } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique
)
$previousValues = @{}
try {
    [Environment]::SetEnvironmentVariable(
        $bindingVariable,
        $bindingPath,
        [EnvironmentVariableTarget]::Process
    )
    if (-not [string]::IsNullOrWhiteSpace($qwenEndpoint)) {
        [Environment]::SetEnvironmentVariable(
            $qwenEndpointVariable,
            $qwenEndpoint,
            [EnvironmentVariableTarget]::Process
        )
    }
    foreach ($credentialName in $credentialNames) {
        $previousValues[$credentialName] = [Environment]::GetEnvironmentVariable(
            $credentialName,
            [EnvironmentVariableTarget]::Process
        )
        $secret = Get-NorthwindLocalSecret -Name $credentialName
        if ($null -ne $secret) {
            [Environment]::SetEnvironmentVariable(
                $credentialName,
                $secret,
                [EnvironmentVariableTarget]::Process
            )
            $secret = $null
        }
    }
    $backendArguments = @(
        '-3.12', '-m', 'uvicorn', 'backend.main:app',
        '--host', '127.0.0.1', '--port', [string]$BackendPort
    )
    if (Test-Path -LiteralPath $envPath -PathType Leaf) {
        $backendArguments += @('--env-file', $envPath)
    }
    $backend = Start-Process -FilePath 'py' -ArgumentList $backendArguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

    foreach ($credentialName in $credentialNames) {
        [Environment]::SetEnvironmentVariable(
            $credentialName,
            $null,
            [EnvironmentVariableTarget]::Process
        )
    }
    [Environment]::SetEnvironmentVariable(
        $qwenEndpointVariable,
        $previousQwenEndpoint,
        [EnvironmentVariableTarget]::Process
    )

    $customer = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--prefix', 'customer', '--', '--host', '127.0.0.1', '--port', [string]$CustomerPort) -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    $workbench = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--prefix', 'workbench', '--', '--host', '127.0.0.1', '--port', [string]$WorkbenchPort) -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    $admin = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--prefix', 'admin', '--', '--host', '127.0.0.1', '--port', [string]$AdminPort) -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
}
finally {
    [Environment]::SetEnvironmentVariable(
        $bindingVariable,
        $previousBindingPath,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        $qwenEndpointVariable,
        $previousQwenEndpoint,
        [EnvironmentVariableTarget]::Process
    )
    foreach ($credentialName in $credentialNames) {
        [Environment]::SetEnvironmentVariable(
            $credentialName,
            $previousValues[$credentialName],
            [EnvironmentVariableTarget]::Process
        )
    }
}

[PSCustomObject]@{
    Backend = "http://127.0.0.1:$BackendPort (PID $($backend.Id))"
    Customer = "http://127.0.0.1:$CustomerPort (PID $($customer.Id))"
    Workbench = "http://127.0.0.1:$WorkbenchPort/workbench/ (PID $($workbench.Id))"
    Admin = "http://127.0.0.1:$AdminPort/admin/ (PID $($admin.Id))"
}
