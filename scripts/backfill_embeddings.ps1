# Backfills embeddings for audit rows stored before embeddings existed:
# embeds prompt/response text with the local embedding model and writes the
# vectors into the sqlite-vec store. Idempotent - safe to re-run.
# Usage: scripts/backfill_embeddings.ps1 [--dry-run] [--batch-size N]
# Requires the embedding model (scripts/download_embedding_model.ps1).

$ErrorActionPreference = "Stop"

$backendDir = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"

# Prefer the backend virtualenv's python; fall back to whatever is on PATH.
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

Push-Location $backendDir
try {
    & $python -m app.audit.embeddings_backfill @args
    if ($LASTEXITCODE -ne 0) {
        throw "embeddings backfill exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
