# One-shot development setup for LunaBlue (Step 18). Idempotent: safe to
# re-run at any time; each step skips or redoes cleanly.
#   1. Checks prerequisites (Python >= 3.11, Node >= 20) with
#      actionable failure messages.
#   2. Creates the Python venv at backend/.venv if missing.
#   3. Installs the backend: pip install -e backend[dev], then the [llm]
#      extra (llama-cpp-python) that the real server needs. On NVIDIA
#      machines the driver's supported CUDA version is detected and a
#      matching prebuilt GPU wheel (plus the pip-packaged CUDA runtime)
#      is installed automatically - no CUDA toolkit needed.
#   4. Installs frontend dependencies: npm ci in frontend/.
#   5. Copies .env.example to .env if absent, and sets LLM_GPU_LAYERS=-1
#      when a GPU build was installed (unless already customized).
# Usage: scripts/setup.ps1
# NOTE: keep this file pure ASCII - Windows PowerShell 5.1 parses BOM-less
# scripts as ANSI, and any multi-byte character breaks it.

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

# -- [1/5] Prerequisites -----------------------------------------------------
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

# Node >= 20 (Vite 7 requires it) - installs come with npm.
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

# No database prerequisite (Step 21): the audit store is a local SQLite
# file (data/lunablue.db) created automatically on first start.

# -- [2/5] Python venv -------------------------------------------------------
Step "[2/5] Python venv (backend/.venv)"
if (Test-Path $venvPython) {
    Write-Host "venv already exists - reusing it."
} else {
    & $pythonExe @pythonArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Fail "creating the venv failed. Remove backend\.venv and re-run."
    }
    Write-Host "venv created."
}

# -- [3/5] Backend install ---------------------------------------------------
Step "[3/5] Installing backend (pip install -e backend[dev])"
& $venvPython -m pip install --quiet -e "$backendDir[dev]"
if ($LASTEXITCODE -ne 0) {
    Fail "backend install failed (see pip output above). Fix the reported issue and re-run."
}
Write-Host "Backend + dev tools installed."

Step "[3/5] Installing the LLM runtime (llama-cpp-python)"
# Install llama-cpp-python from a prebuilt wheel index, never from the
# PyPI sdist: a source build needs CMake + a C++ toolchain AND (on Windows)
# long paths enabled - the vendored llama.cpp tree nests deep enough that
# sdist extraction fails with a misleading "Errno 2 No such file or
# directory" under the default 260-char MAX_PATH limit. --only-binary
# forbids that fallback outright.
#
# The wheel tier is picked per machine: nvidia-smi reports the driver's
# maximum supported CUDA version, and app.llm.native.pick_wheel_tier maps
# it to the matching CUDA wheel index (cu130 for 13.0+, cu124 for 12.4+,
# CPU otherwise). The CUDA runtime DLLs come from the nvidia-* pip
# packages, so no CUDA toolkit install is required.
$tier = "cpu"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $smiOut = @()
    try { $smiOut = & nvidia-smi } catch { $smiOut = @() }
    if ($smiOut) {
        $tier = $smiOut | & $venvPython -c "import sys; from app.llm.native import pick_wheel_tier; print(pick_wheel_tier(sys.stdin.read()))"
        if ($LASTEXITCODE -ne 0 -or -not $tier) { $tier = "cpu" }
        $tier = "$tier".Trim()
    }
}

$wheelIndex = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
$runtimePkgs = @()
if ($tier -eq "cu130") {
    $wheelIndex = "https://abetlen.github.io/llama-cpp-python/whl/cu130"
    $runtimePkgs = @("nvidia-cuda-runtime-cu13", "nvidia-cublas-cu13")
    Write-Host "NVIDIA driver supports CUDA 13+: selecting the cu130 GPU wheel."
} elseif ($tier -eq "cu124") {
    $wheelIndex = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
    $runtimePkgs = @("nvidia-cuda-runtime-cu12", "nvidia-cublas-cu12")
    Write-Host "NVIDIA driver supports CUDA 12.4+: selecting the cu124 GPU wheel."
} elseif ($tier -eq "cpu-old-driver") {
    Write-Host "NVIDIA GPU found, but its driver is too old for the prebuilt CUDA wheels (they need CUDA 12.4+ driver support). Installing the CPU build. Update your driver (https://www.nvidia.com/drivers) and re-run scripts\setup.ps1 to enable GPU inference." -ForegroundColor Yellow
}
$gpuWanted = ($runtimePkgs.Count -gt 0)

# Idempotency: skip the install only when the existing build already
# matches intent (probe states: missing / broken / cpu / gpu). Each probe
# runs in a fresh python process - a reinstalled wheel cannot be
# re-imported into a process that already loaded the old one.
$state = & $venvPython -c "from app.llm.native import probe_install_state; print(probe_install_state())"
if ($LASTEXITCODE -ne 0) { $state = "broken" }
$state = "$state".Trim()

$gpuActive = $false
$needInstall = $true
if ($gpuWanted -and $state -eq "gpu") {
    Write-Host "llama-cpp-python with GPU offload already installed - leaving it untouched."
    $gpuActive = $true
    $needInstall = $false
} elseif (-not $gpuWanted -and ($state -eq "gpu" -or $state -eq "cpu")) {
    Write-Host "llama-cpp-python already installed - leaving it untouched."
    $needInstall = $false
}

if ($needInstall) {
    if ($gpuWanted) {
        & $venvPython -m pip install --quiet --only-binary=:all: $runtimePkgs
        if ($LASTEXITCODE -ne 0) {
            Fail "installing the NVIDIA CUDA runtime packages ($($runtimePkgs -join ', ')) failed (see pip output above)."
        }
    }
    & $venvPython -m pip install --quiet llama-cpp-python --force-reinstall --no-cache-dir --only-binary=:all: `
        --index-url $wheelIndex `
        --extra-index-url https://pypi.org/simple
    if ($LASTEXITCODE -ne 0) {
        Fail @"
llama-cpp-python install failed. Retry the prebuilt wheel directly:
  backend\.venv\Scripts\pip install llama-cpp-python --only-binary=:all: --index-url $wheelIndex --extra-index-url https://pypi.org/simple
If you must build from source instead (not recommended), you need CMake and
a C++ toolchain (Visual Studio Build Tools on Windows) AND Windows long
paths enabled (LongPathsEnabled=1) - an "Errno 2" failure on a deep
vendor\llama.cpp\... path means long paths are off, not that a file is
missing. See backend/README.md (Install variants), incl. GPU builds.
"@
    }
    if ($gpuWanted) {
        # Verify the GPU wheel actually initializes here; if not, fall back
        # to the CPU wheel so setup still ends in a working state.
        $state = & $venvPython -c "from app.llm.native import probe_install_state; print(probe_install_state())"
        if ($LASTEXITCODE -eq 0 -and "$state".Trim() -eq "gpu") {
            $gpuActive = $true
            Write-Host "GPU build verified: llama.cpp reports GPU offload support." -ForegroundColor Green
        } else {
            Write-Host "warning: the $tier GPU wheel did not initialize on this machine - falling back to the CPU build. Update your NVIDIA driver and re-run setup to retry GPU." -ForegroundColor Yellow
            & $venvPython -m pip install --quiet llama-cpp-python --force-reinstall --no-cache-dir --only-binary=:all: `
                --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu `
                --extra-index-url https://pypi.org/simple
            if ($LASTEXITCODE -ne 0) {
                Fail "CPU fallback install failed (see pip output above)."
            }
        }
    }
}
& $venvPython -m pip install --quiet -e "$backendDir[dev,llm]"
if ($LASTEXITCODE -ne 0) {
    Fail "backend[dev,llm] install failed (see pip output above). Fix the reported issue and re-run."
}
if ($gpuActive) {
    Write-Host "LLM runtime installed (GPU-accelerated, $tier)."
} else {
    Write-Host "LLM runtime installed (CPU)."
}

# -- [4/5] Frontend install --------------------------------------------------
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

# -- [5/5] .env --------------------------------------------------------------
Step "[5/5] Environment file"
$envFile = Join-Path $repoRoot ".env"
if (Test-Path $envFile) {
    Write-Host ".env already exists - leaving it untouched."
} else {
    Copy-Item (Join-Path $repoRoot ".env.example") $envFile
    Write-Host ".env created from .env.example (defaults are fine for local use)."
}

# A verified GPU build defaults to full offload for both the chat and the
# embedding model. Only the absent/0 cases are touched - any other
# explicit value is the user's.
if ($gpuActive) {
    foreach ($gpuKey in @("LLM_GPU_LAYERS", "EMBEDDING_GPU_LAYERS")) {
        $envLines = @(Get-Content $envFile)
        $current = $envLines | Where-Object { $_ -match "^\s*$gpuKey\s*=" } | Select-Object -First 1
        if (-not $current) {
            Add-Content -Path $envFile -Value "$gpuKey=-1" -Encoding Ascii
            Write-Host "$gpuKey=-1 appended to .env (offload all layers to the GPU)."
        } elseif ($current -match "^\s*$gpuKey\s*=\s*0\s*$") {
            $envLines = $envLines -replace "^\s*$gpuKey\s*=\s*0\s*$", "$gpuKey=-1"
            Set-Content -Path $envFile -Value $envLines -Encoding Ascii
            Write-Host "$gpuKey changed 0 -> -1 in .env (offload all layers to the GPU)."
        } else {
            Write-Host ".env keeps your existing $gpuKey value."
        }
    }
}

Write-Host ""
if ($gpuActive) {
    Write-Host "LLM inference: GPU ($tier wheel, CUDA runtime from pip)." -ForegroundColor Green
} else {
    Write-Host "LLM inference: CPU."
}
Write-Host "Setup complete. Next steps (from the repo root):" -ForegroundColor Green
Write-Host "  1. scripts\download_model.ps1     (~2.3 GB, one-time)"
Write-Host "  2. scripts\build_frontend.ps1"
Write-Host "  3. cd backend; .venv\Scripts\uvicorn app.main:app --port 8000"
Write-Host "  4. open http://localhost:8000/"
Write-Host "The audit database (data\lunablue.db) is created automatically on first start."
