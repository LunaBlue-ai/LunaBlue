# Builds the React frontend and copies the bundle into backend/app/static/
# so a single FastAPI process serves both the UI and the API
# (docs/Architecture.md). Usage: scripts/build_frontend.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $repoRoot "frontend"
$staticDir = Join-Path $repoRoot "backend\app\static"
$distDir = Join-Path $frontendDir "dist"

Push-Location $frontendDir
try {
    if (Test-Path (Join-Path $frontendDir "package-lock.json")) {
        npm ci
    } else {
        npm install
    }
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed with exit code $LASTEXITCODE"
    }

    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "npm run build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $distDir "index.html"))) {
    throw "Build succeeded but $distDir\index.html is missing"
}

# Clear the previous bundle but keep the .gitkeep that pins the (otherwise
# gitignored) directory in the repository.
if (-not (Test-Path $staticDir)) {
    New-Item -ItemType Directory -Force $staticDir | Out-Null
}
Get-ChildItem $staticDir -Force | Where-Object { $_.Name -ne ".gitkeep" } |
    Remove-Item -Recurse -Force -Confirm:$false

Copy-Item -Recurse -Force (Join-Path $distDir "*") $staticDir

if (-not (Test-Path (Join-Path $staticDir "index.html"))) {
    throw "Copy failed: $staticDir\index.html is missing"
}

Write-Host "Frontend bundle copied to $staticDir"
Write-Host "Start the backend (uvicorn app.main:app --port 8000) and open http://localhost:8000/"
