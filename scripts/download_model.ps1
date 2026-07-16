# Downloads the default GGUF model into models/ for the local LLM runtime.
# Default: Phi-3-mini-4k-instruct Q4 (MIT license, ~2.3 GB, CPU-friendly),
# saved as models/model.gguf to match .env.example's MODEL_PATH default.
# Usage: scripts/download_model.ps1 [-Url <gguf url>] [-OutFile <path>]
# See models/README.md for substituting another model.

param(
    [string]$Url = "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$modelsDir = Join-Path $repoRoot "models"
if (-not (Test-Path $modelsDir)) {
    New-Item -ItemType Directory -Force $modelsDir | Out-Null
}
if (-not $OutFile) {
    $OutFile = Join-Path $modelsDir "model.gguf"
}

if (Test-Path $OutFile) {
    Write-Host "Model already present: $OutFile"
    Write-Host "Delete it first to re-download."
    exit 0
}

# Download to a temp name and rename on success, so an interrupted download
# never leaves a partial file where MODEL_PATH expects a complete one.
$partial = "$OutFile.partial"

Write-Host "Downloading $Url"
Write-Host "       to $OutFile (~2.3 GB, this can take a while)"

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
Write-Host "Done. Model saved to $OutFile"
Write-Host "MODEL_PATH in .env.example already points here (./models/model.gguf)."
