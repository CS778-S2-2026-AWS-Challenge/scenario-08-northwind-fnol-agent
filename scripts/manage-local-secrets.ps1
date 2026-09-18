param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('set', 'list', 'remove')]
    [string]$Action,

    [Parameter(Position = 1)]
    [string]$Name
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Northwind.LocalSecrets.psm1') -Force

switch ($Action) {
    'set' {
        if ([string]::IsNullOrWhiteSpace($Name)) { throw 'set requires a credential name.' }
        $value = Read-Host "Enter $Name" -AsSecureString
        Set-NorthwindLocalSecret -Name $Name -Value $value
        Write-Output "Stored $Name for the current Windows user."
    }
    'list' {
        Get-NorthwindLocalSecretMetadata | Format-Table -AutoSize
    }
    'remove' {
        if ([string]::IsNullOrWhiteSpace($Name)) { throw 'remove requires a credential name.' }
        $removed = Remove-NorthwindLocalSecret -Name $Name
        Write-Output ($(if ($removed) { "Removed $Name." } else { "$Name was not registered." }))
    }
}
