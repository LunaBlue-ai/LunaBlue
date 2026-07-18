# Downloads the default embedding GGUF model into models/ for semantic
# search. Default: nomic-embed-text-v1.5 Q8 (Apache-2.0, ~140 MB), saved as
# models/embedding.gguf to match .env.example's EMBEDDING_MODEL_PATH default.
# Usage: scripts/download_embedding_model.ps1 [-Url <gguf url>] [-OutFile <path>]
# See models/README.md for substituting another model.

param(
    [string]$Url = "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$modelsDir = Join-Path $repoRoot "models"
if (-not (Test-Path $modelsDir)) {
    New-Item -ItemType Directory -Force $modelsDir | Out-Null
}
if (-not $OutFile) {
    $OutFile = Join-Path $modelsDir "embedding.gguf"
}

if (Test-Path $OutFile) {
    Write-Host "Embedding model already present: $OutFile"
    Write-Host "Delete it first to re-download."
    exit 0
}

# Download to a temp name and rename on success, so an interrupted download
# never leaves a partial file where EMBEDDING_MODEL_PATH expects a complete one.
$partial = "$OutFile.partial"

Write-Host "Downloading $Url"
Write-Host "       to $OutFile (~140 MB)"

# curl.exe (bundled with Windows 10+) handles large files and resume (-C -)
# far better than Invoke-WebRequest; fall back to the latter if missing.
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($curl) {
    & $curl.Source -L --fail --retry 3 -C - -o $partial $Url
    if ($LASTEXITCODE -ne 0) {
        throw "curl exited with code $LASTEXITCODE"
    }
} else {
    Invoke-WebRequest -Uri $Url -OutFile $partial
}

Move-Item -Force $partial $OutFile
Write-Host "Done. Embedding model saved to $OutFile"
Write-Host "EMBEDDING_MODEL_PATH in .env.example already points here (./models/embedding.gguf)."
