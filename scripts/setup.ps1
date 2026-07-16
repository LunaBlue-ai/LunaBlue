# One-shot development setup for LunaBlue (Step 18). Idempotent: safe to
# re-run at any time; each step skips or redoes cleanly.
#   1. Checks prerequisites (Python >= 3.11, Node >= 20, Docker) with
#      actionable failure messages.
#   2. Creates the Python venv at backend/.venv if missing.
#   3. Installs the backend: pip install -e backend[dev], then the [llm]
#      extra (llama-cpp-python) that the real server needs.
#   4. Installs frontend dependencies: npm ci in frontend/.
#   5. Copies .env.example to .env if absent.
# Usage: scripts/setup.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Step([string]$Message) {
    Write-Host ""
    Write-Host "== $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host "error: $Message" -ForegroundColor Red
    exit 1
}

# ── [1/5] Prerequisites ─────────────────────────────────────────────────────
Step "[1/5] Checking prerequisites"

# Python >= 3.11. Prefer the Windows launcher, fall back to python on PATH.
$pythonExe = $null
$pythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
}
if (-not $pythonExe) {
    Fail "Python not found. Install Python 3.11+ from https://www.python.org/downloads/ and re-run."
}
$pyVersion = & $pythonExe @pythonArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3]); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Fail "Python $pyVersion found, but LunaBlue needs 3.11+. Install a newer Python from https://www.python.org/downloads/ and re-run."
}
Write-Host "Python $pyVersion  OK"

# Node >= 20 (Vite 7 requires it) — installs come with npm.
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Fail "Node.js not found. Install Node 22 LTS from https://nodejs.org/ and re-run."
}
$nodeVersion = (node --version).TrimStart("v")
$nodeMajor = [int]$nodeVersion.Split(".")[0]
if ($nodeMajor -lt 20) {
    Fail "Node $nodeVersion found, but the frontend toolchain (Vite 7) needs Node 20+. Install Node 22 LTS from https://nodejs.org/ and re-run."
}
Write-Host "Node $nodeVersion  OK"

# Docker CLI — needed for the Postgres audit store (docker compose).
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Fail "Docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and re-run. LunaBlue uses it for the Postgres audit database (docker compose up -d postgres)."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker CLI found, but the daemon is not running. Setup can continue; start Docker Desktop before 'docker compose up -d postgres'." -ForegroundColor Yellow
} else {
    Write-Host "Docker $((docker --version) -replace 'Docker version ', '' -replace ',.*', '')  OK"
}

# ── [2/5] Python venv ───────────────────────────────────────────────────────
Step "[2/5] Python venv (backend/.venv)"
if (Test-Path $venvPython) {
    Write-Host "venv already exists — reusing it."
} else {
    & $pythonExe @pythonArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Fail "creating the venv failed. Remove backend\.venv and re-run."
    }
    Write-Host "venv created."
}

# ── [3/5] Backend install ───────────────────────────────────────────────────
Step "[3/5] Installing backend (pip install -e backend[dev])"
& $venvPython -m pip install --quiet -e "$backendDir[dev]"
if ($LASTEXITCODE -ne 0) {
    Fail "backend install failed (see pip output above). Fix the reported issue and re-run."
}
Write-Host "Backend + dev tools installed."

Step "[3/5] Installing the LLM runtime (backend[llm]: llama-cpp-python, CPU build)"
& $venvPython -m pip install --quiet -e "$backendDir[dev,llm]"
if ($LASTEXITCODE -ne 0) {
    Fail @"
llama-cpp-python install failed. It ships prebuilt wheels for common
platforms; when pip falls back to a source build it needs CMake and a C++
toolchain (Visual Studio Build Tools on Windows). Alternatives:
  - install build tools, then re-run this script, or
  - use the project's wheel index:
      backend\.venv\Scripts\pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
See backend/README.md (Install variants) for GPU builds.
"@
}
Write-Host "LLM runtime installed."

# ── [4/5] Frontend install ──────────────────────────────────────────────────
Step "[4/5] Installing frontend dependencies (npm ci)"
Push-Location $frontendDir
try {
    npm ci --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) {
        Fail "npm ci failed (see output above). Fix the reported issue and re-run."
    }
} finally {
    Pop-Location
}
Write-Host "Frontend dependencies installed."

# ── [5/5] .env ──────────────────────────────────────────────────────────────
Step "[5/5] Environment file"
$envFile = Join-Path $repoRoot ".env"
if (Test-Path $envFile) {
    Write-Host ".env already exists — leaving it untouched."
} else {
    Copy-Item (Join-Path $repoRoot ".env.example") $envFile
    Write-Host ".env created from .env.example (defaults are fine for local use)."
}

Write-Host ""
Write-Host "Setup complete. Next steps (from the repo root):" -ForegroundColor Green
Write-Host "  1. docker compose up -d postgres"
Write-Host "  2. scripts\migrate.ps1"
Write-Host "  3. scripts\download_model.ps1     (~2.3 GB, one-time)"
Write-Host "  4. scripts\build_frontend.ps1"
Write-Host "  5. cd backend; .venv\Scripts\uvicorn app.main:app --port 8000"
Write-Host "  6. open http://localhost:8000/"
