param(
    [ValidateSet('hardened', 'baseline', 'unprotected')]
    [string]$Profile = 'hardened'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI is required for the Compose smoke test.'
}

docker compose --env-file .env --env-file "profiles/$Profile.env" config --quiet
docker compose --env-file .env --env-file "profiles/$Profile.env" up --build -d --wait

try {
    $health = Invoke-RestMethod -SkipCertificateCheck https://localhost/
    if (-not $health) { throw 'Nginx/frontend returned an empty response.' }
    docker compose ps
    Write-Host "Compose smoke test passed with profile '$Profile'." -ForegroundColor Green
} catch {
    docker compose ps
    docker compose logs --tail 200
    throw
}
