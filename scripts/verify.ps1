$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Push-Location (Join-Path $Root 'cfms_on_websocket-master')
try {
    Invoke-Checked 'Core dependency sync' {
        uv sync --python 3.14 --extra cluster --extra mysql --extra ext_oidc_sso --group dev
    }
    Invoke-Checked 'Core Ruff' { uvx ruff check . }
    # Use the interpreter directly: copied/moved Windows worktrees can leave an
    # old uv executable trampoline even after dependency metadata is refreshed.
    Invoke-Checked 'Core pytest' { & .venv\Scripts\python.exe -m pytest -q }
    Push-Location 'src'
    try {
        $Heads = @(& ..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads)
        if ($LASTEXITCODE -ne 0) {
            throw "Alembic head validation failed with exit code $LASTEXITCODE"
        }
        $Heads | ForEach-Object { Write-Host $_ }
        if ($Heads.Count -ne 1 -or $Heads[0] -notmatch '\(head\)$') {
            throw "Expected exactly one Alembic head, got: $($Heads -join ', ')"
        }
    } finally { Pop-Location }
} finally { Pop-Location }

Push-Location (Join-Path $Root 'carapace')
try {
    Invoke-Checked 'Security Gateway Gradle' {
        & .\gradlew.bat clean test bootJar --no-daemon
    }
} finally { Pop-Location }

Push-Location (Join-Path $Root 'transfer-data-plane')
try {
    Invoke-Checked 'Transfer Data Plane Gradle' {
        & .\gradlew.bat clean test bootJar --no-daemon
    }
} finally { Pop-Location }

Push-Location (Join-Path $Root 'thesis_frontend')
try {
    Invoke-Checked 'Frontend dependency install' { npm ci }
    Invoke-Checked 'Frontend Vitest' { npm test -- --run }
    Invoke-Checked 'Frontend production build' { npm run build }
} finally { Pop-Location }

Push-Location $Root
try {
    Invoke-Checked 'Benchmark contract tests' {
        python -m unittest discover -s benchmarks\tests -v
    }
    Invoke-Checked 'Git whitespace validation' { git diff --check }
} finally { Pop-Location }

Write-Host 'All local verification suites passed.' -ForegroundColor Green
