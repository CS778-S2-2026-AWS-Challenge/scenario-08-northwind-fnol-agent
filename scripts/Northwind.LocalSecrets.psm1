Set-StrictMode -Version Latest

function Get-NorthwindSecretRoot {
    $root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Northwind\secrets'
    return $root
}

function Assert-NorthwindCredentialName {
    param([Parameter(Mandatory)][string]$Name)

    if ($Name -notmatch '^[A-Z][A-Z0-9_]{0,127}$') {
        throw 'Credential names must use uppercase environment-variable syntax.'
    }
}

function Get-NorthwindSecretPath {
    param([Parameter(Mandatory)][string]$Name)

    Assert-NorthwindCredentialName -Name $Name
    return Join-Path (Get-NorthwindSecretRoot) "$Name.dpapi"
}

function Set-NorthwindLocalSecret {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Security.SecureString]$Value
    )

    $path = Get-NorthwindSecretPath -Name $Name
    $root = Split-Path -Parent $path
    [IO.Directory]::CreateDirectory($root) | Out-Null
    $pointer = [IntPtr]::Zero
    $plaintext = $null
    $bytes = $null
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        $plaintext = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plaintext)) {
            throw 'Credential values must not be empty.'
        }
        $bytes = [Text.Encoding]::UTF8.GetBytes($plaintext)
        $protected = [Security.Cryptography.ProtectedData]::Protect(
            $bytes,
            $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        [IO.File]::WriteAllBytes($path, $protected)
    }
    finally {
        if ($bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        $plaintext = $null
    }
}

function Get-NorthwindLocalSecret {
    param([Parameter(Mandatory)][string]$Name)

    $path = Get-NorthwindSecretPath -Name $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $protected = [IO.File]::ReadAllBytes($path)
    $bytes = $null
    try {
        $bytes = [Security.Cryptography.ProtectedData]::Unprotect(
            $protected,
            $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        return [Text.Encoding]::UTF8.GetString($bytes)
    }
    finally {
        if ($bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
    }
}

function Remove-NorthwindLocalSecret {
    param([Parameter(Mandatory)][string]$Name)

    $path = Get-NorthwindSecretPath -Name $Name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
        return $true
    }
    return $false
}

function Get-NorthwindLocalSecretMetadata {
    $root = Get-NorthwindSecretRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return @() }
    return @(
        Get-ChildItem -LiteralPath $root -Filter '*.dpapi' -File |
            Sort-Object Name |
            ForEach-Object {
                [PSCustomObject]@{
                    Name = $_.BaseName
                    UpdatedAtUtc = $_.LastWriteTimeUtc.ToString('o')
                }
            }
    )
}

Export-ModuleMember -Function @(
    'Get-NorthwindSecretRoot',
    'Set-NorthwindLocalSecret',
    'Get-NorthwindLocalSecret',
    'Remove-NorthwindLocalSecret',
    'Get-NorthwindLocalSecretMetadata'
)
