# Applies the audit retention policy: deletes audit rows older than the
# configured window (AUDIT_RETENTION_DAYS / AUDIT_RETENTION_OVERRIDES in .env).
# Usage: scripts/retention.ps1 [--dry-run] [--days N]
# Schedule with Windows Task Scheduler for unattended enforcement; see
# docs/DataRetention.md.

$ErrorActionPreference = "Stop"

$backendDir = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"

# Prefer the backend virtualenv's python; fall back to whatever is on PATH.
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

Push-Location $backendDir
try {
    & $python -m app.audit.retention @args
    if ($LASTEXITCODE -ne 0) {
        throw "retention exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
