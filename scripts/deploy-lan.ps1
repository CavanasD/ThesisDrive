[CmdletBinding()]
param(
    [ValidateSet('hardened', 'baseline', 'course-unprotected', 'unprotected')]
    [string]$Profile = 'hardened',

    [string]$EnvFile = '',

    [switch]$NoBuild,

    [switch]$AllowNonPrivateLabAddress,

    [switch]$AllowExtendedVulnerabilities
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $EnvFile) {
    $EnvFile = Join-Path $Root '.env'
}
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)
$ProfileFile = Join-Path $Root "profiles/$Profile.env"

function Read-DotEnv {
    param([string]$Path)

    $result = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) {
            continue
        }
        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) {
            continue
        }
        $result[$trimmed.Substring(0, $separator)] = $trimmed.Substring($separator + 1)
    }
    return $result
}

function Test-PrivateIpv4 {
    param([System.Net.IPAddress]$Address)

    $bytes = $Address.GetAddressBytes()
    return $bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168) -or
        $bytes[0] -eq 127
}

function Invoke-Docker {
    param([string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7 or newer is required.'
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Environment file not found: $EnvFile. Run prepare-lan-env.ps1 first."
}
if (-not (Test-Path -LiteralPath $ProfileFile)) {
    throw "Profile file not found: $ProfileFile"
}
$environment = Read-DotEnv $EnvFile
foreach ($name in @(
    'BIND_ADDRESS',
    'TLS_SAN',
    'MYSQL_ROOT_PASSWORD',
    'MYSQL_PASSWORD',
    'REDIS_PASSWORD',
    'MINIO_ROOT_PASSWORD',
    'CARAPACE_ADMIN_TOKEN',
    'GRAFANA_ADMIN_PASSWORD',
    'PUBLIC_ORIGINS'
)) {
    if (-not $environment[$name] -or $environment[$name] -like 'change-this-*') {
        throw "Missing or unsafe value for $name in $EnvFile"
    }
}

$bindIp = $null
if (-not [System.Net.IPAddress]::TryParse($environment.BIND_ADDRESS, [ref]$bindIp) -or
    $bindIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'BIND_ADDRESS must be one exact IPv4 address.'
}
if ($bindIp.Equals([System.Net.IPAddress]::Any) -or
    $bindIp.Equals([System.Net.IPAddress]::Broadcast)) {
    throw 'BIND_ADDRESS cannot be a wildcard or broadcast address.'
}
if ($Profile -ne 'hardened' -and
    -not (Test-PrivateIpv4 $bindIp) -and
    -not $AllowNonPrivateLabAddress) {
    throw "Profile '$Profile' exposes teaching vulnerabilities. Use an RFC1918/loopback address or explicitly pass -AllowNonPrivateLabAddress after applying network ACLs."
}
if ($Profile -eq 'unprotected' -and -not $AllowExtendedVulnerabilities) {
    throw "Profile 'unprotected' also enables SSRF, JWT alg=none, reflected CORS, and JNDI lookup exercises. Use 'course-unprotected' for the assigned tasks, or explicitly pass -AllowExtendedVulnerabilities for a separately authorized exercise."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI with Compose v2 is required on the deployment host.'
}

Push-Location $Root
try {
    Invoke-Docker @('compose', 'version')
    $compose = @('compose', '--env-file', $EnvFile, '--env-file', $ProfileFile)
    Invoke-Docker ($compose + @('config', '--quiet'))

    $up = $compose + @('up')
    if (-not $NoBuild) {
        $up += '--build'
    }
    $up += @('-d', '--wait')
    Invoke-Docker $up

    $healthUrl = "https://$($bindIp.IPAddressToString)/"
    $response = Invoke-WebRequest -Uri $healthUrl -SkipCertificateCheck -TimeoutSec 20
    if ($response.StatusCode -ne 200) {
        throw "Unexpected HTTPS status: $($response.StatusCode)"
    }

    $safeAddress = $bindIp.IPAddressToString.Replace('.', '-')
    $certificatePath = Join-Path ([System.IO.Path]::GetTempPath()) "thesis-drive-$safeAddress-tls.crt"
    Invoke-Docker ($compose + @('cp', 'nginx:/etc/nginx/certs/tls.crt', $certificatePath))

    $profileMessage = switch ($Profile) {
        'hardened' { 'LAB disabled; WAF enabled.' }
        'baseline' { 'LAB simulations enabled; WAF enabled for interception evidence.' }
        'course-unprotected' { 'Assigned LAB simulations enabled; WAF disabled; extended gateway exercises disabled.' }
        'unprotected' { 'All LAB and extended gateway exercises enabled; WAF disabled. Keep this instance isolated.' }
    }
    Write-Host "Deployment passed: $healthUrl" -ForegroundColor Green
    Write-Host "Profile: $Profile - $profileMessage"
    Write-Host "Client trust certificate: $certificatePath"
    Write-Host 'Read the initial admin password with:'
    Write-Host "docker compose --env-file `"$EnvFile`" --env-file `"$ProfileFile`" exec -T drive-core cat /app/state/admin_password.txt"
} catch {
    Write-Host 'Deployment failed. Current service state:' -ForegroundColor Red
    & docker compose --env-file $EnvFile --env-file $ProfileFile ps 2>$null
    throw
} finally {
    Pop-Location
}
