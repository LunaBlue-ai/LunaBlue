# Runs Alembic migrations (upgrade head) against the configured database.
# The database URL comes from DATABASE_URL / .env via the app settings.
# Usage: scripts/migrate.ps1 [extra alembic args, e.g. downgrade base]

$ErrorActionPreference = "Stop"

$backendDir = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"

# Prefer the backend virtualenv's alembic; fall back to whatever is on PATH.
$alembic = Join-Path $backendDir ".venv\Scripts\alembic.exe"
if (-not (Test-Path $alembic)) {
    $alembic = "alembic"
}

$alembicArgs = if ($args.Count -gt 0) { $args } else { @("upgrade", "head") }

Push-Location $backendDir
try {
    & $alembic @alembicArgs
    if ($LASTEXITCODE -ne 0) {
        throw "alembic exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
