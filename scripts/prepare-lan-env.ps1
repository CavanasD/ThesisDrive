[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BindAddress,

    [string]$PublicHost = $BindAddress,

    [string]$OutputPath = '',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$TemplatePath = Join-Path $Root '.env.example'
if (-not $OutputPath) {
    $OutputPath = Join-Path $Root '.env'
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$bindIp = $null
if (-not [System.Net.IPAddress]::TryParse($BindAddress, [ref]$bindIp) -or
    $bindIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'BindAddress must be one exact IPv4 address, not a hostname or CIDR.'
}
if ($bindIp.Equals([System.Net.IPAddress]::Any) -or
    $bindIp.Equals([System.Net.IPAddress]::Broadcast)) {
    throw 'Wildcard and broadcast bind addresses are not allowed for the lab deployment.'
}
$BindAddress = $bindIp.IPAddressToString

$PublicHost = $PublicHost.Trim()
if (-not $PublicHost -or $PublicHost -match '[:/\\\s]') {
    throw 'PublicHost must be one IPv4 address or DNS hostname without a scheme, path, or port.'
}

$publicIp = $null
$publicHostIsIp = [System.Net.IPAddress]::TryParse($PublicHost, [ref]$publicIp)
if ($publicHostIsIp) {
    if ($publicIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'Only IPv4 public addresses are supported by this deployment helper.'
    }
    $PublicHost = $publicIp.IPAddressToString
} elseif ($PublicHost -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$') {
    throw 'PublicHost is not a valid DNS hostname.'
}

if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "Environment file already exists: $OutputPath. Use -Force to replace it."
}
if (-not (Test-Path -LiteralPath $TemplatePath)) {
    throw "Environment template not found: $TemplatePath"
}

function New-RandomSecret {
    $buffer = [byte[]]::new(24)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$tlsSans = [System.Collections.Generic.List[string]]::new()
foreach ($san in @(
    'DNS:localhost',
    'IP:127.0.0.1',
    "IP:$BindAddress",
    $(if ($publicHostIsIp) { "IP:$PublicHost" } else { "DNS:$PublicHost" })
)) {
    if (-not $tlsSans.Contains($san)) {
        $tlsSans.Add($san)
    }
}

$origins = [System.Collections.Generic.List[string]]::new()
foreach ($origin in @("https://$PublicHost", "https://$BindAddress", 'https://localhost', 'https://127.0.0.1')) {
    if (-not $origins.Contains($origin)) {
        $origins.Add($origin)
    }
}

$values = [ordered]@{
    BIND_ADDRESS           = $BindAddress
    TLS_SAN                = $tlsSans -join ','
    MYSQL_ROOT_PASSWORD    = New-RandomSecret
    MYSQL_PASSWORD         = New-RandomSecret
    REDIS_PASSWORD         = New-RandomSecret
    MINIO_ROOT_USER        = 'thesis-minio'
    MINIO_ROOT_PASSWORD    = New-RandomSecret
    CARAPACE_ADMIN_TOKEN   = New-RandomSecret
    GRAFANA_ADMIN_PASSWORD = New-RandomSecret
    GRAFANA_ROOT_URL       = "https://$PublicHost/grafana/"
    PUBLIC_ORIGINS         = $origins -join ','
}

$contents = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8
foreach ($entry in $values.GetEnumerator()) {
    $pattern = '(?m)^' + [Regex]::Escape($entry.Key) + '=.*$'
    if (-not [Regex]::IsMatch($contents, $pattern)) {
        throw "Missing $($entry.Key) in $TemplatePath"
    }
    $replacement = "$($entry.Key)=$($entry.Value)"
    $contents = [Regex]::Replace($contents, $pattern, $replacement)
}

$parent = Split-Path -Parent $OutputPath
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent | Out-Null
}
[System.IO.File]::WriteAllText($OutputPath, $contents, [System.Text.UTF8Encoding]::new($false))

Write-Host "Created LAN environment file: $OutputPath" -ForegroundColor Green
Write-Host "Public URL: https://$PublicHost/"
Write-Host 'Secrets were generated locally and were not printed.'
Write-Host 'Next: pwsh ./scripts/deploy-lan.ps1 -Profile hardened'
