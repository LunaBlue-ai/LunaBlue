#!/usr/bin/env sh
# One-shot development setup for LunaBlue (Step 18). Idempotent: safe to
# re-run at any time; each step skips or redoes cleanly.
#   1. Checks prerequisites (Python >= 3.11, Node >= 20) with
#      actionable failure messages.
#   2. Creates the Python venv at backend/.venv if missing.
#   3. Installs the backend: pip install -e backend[dev], then the [llm]
#      extra (llama-cpp-python) that the real server needs.
#   4. Installs frontend dependencies: npm ci in frontend/.
#   5. Copies .env.example to .env if absent.
# Usage: scripts/setup.sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root="$script_dir/.."
backend_dir="$repo_root/backend"
frontend_dir="$repo_root/frontend"
venv_dir="$backend_dir/.venv"
venv_python="$venv_dir/bin/python"

step() {
    printf '\n== %s\n' "$1"
}

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

# -- [1/5] Prerequisites ----------------------------------------------------
step "[1/5] Checking prerequisites"

python=""
for candidate in python3 python; do
    if command -v "$candidate" > /dev/null 2>&1; then
        python=$candidate
        break
    fi
done
[ -n "$python" ] || fail "Python not found. Install Python 3.11+ (https://www.python.org/downloads/ or your package manager) and re-run."
py_version=$("$python" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "Python $py_version found, but LunaBlue needs 3.11+. Install a newer Python and re-run."
echo "Python $py_version  OK"

command -v node > /dev/null 2>&1 \
    || fail "Node.js not found. Install Node 22 LTS (https://nodejs.org/) and re-run."
node_version=$(node --version | sed 's/^v//')
node_major=${node_version%%.*}
[ "$node_major" -ge 20 ] \
    || fail "Node $node_version found, but the frontend toolchain (Vite 7) needs Node 20+. Install Node 22 LTS and re-run."
echo "Node $node_version  OK"

# No database prerequisite (Step 21): the audit store is a local SQLite
# file (data/lunablue.db) created automatically on first start.

# -- [2/5] Python venv ------------------------------------------------------
step "[2/5] Python venv (backend/.venv)"
if [ -x "$venv_python" ]; then
    echo "venv already exists - reusing it."
else
    "$python" -m venv "$venv_dir"
    [ -x "$venv_python" ] || fail "creating the venv failed. Remove backend/.venv and re-run. (On Debian/Ubuntu you may need: apt install python3-venv)"
    echo "venv created."
fi

# -- [3/5] Backend install --------------------------------------------------
step "[3/5] Installing backend (pip install -e backend[dev])"
"$venv_python" -m pip install --quiet -e "$backend_dir[dev]" \
    || fail "backend install failed (see pip output above). Fix the reported issue and re-run."
echo "Backend + dev tools installed."

step "[3/5] Installing the LLM runtime (llama-cpp-python, prebuilt CPU wheel)"
# Install llama-cpp-python from the project's wheel index, never from the
# PyPI sdist: a source build needs CMake + a C++ toolchain, and pip may
# prefer a newer sdist over an older wheel without --only-binary. Skipped
# when any build (e.g. a GPU wheel, see backend/README.md) is installed.
if "$venv_python" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('llama_cpp') else 1)"; then
    echo "llama-cpp-python already installed - leaving it untouched (GPU builds stay intact)."
elif ! "$venv_python" -m pip install --quiet llama-cpp-python --only-binary=:all: \
        --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
        --extra-index-url https://pypi.org/simple; then
    fail "llama-cpp-python install failed. Retry the prebuilt CPU wheel directly: backend/.venv/bin/pip install llama-cpp-python --only-binary=:all: --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --extra-index-url https://pypi.org/simple. Building from source instead needs CMake and a C++ toolchain (build-essential + cmake on Debian/Ubuntu, Xcode CLT on macOS) - see backend/README.md (Install variants), incl. GPU builds."
fi
"$venv_python" -m pip install --quiet -e "$backend_dir[dev,llm]" \
    || fail "backend[dev,llm] install failed (see pip output above). Fix the reported issue and re-run."
echo "LLM runtime installed."

# NVIDIA GPU present? The default install above is CPU-only and silently
# ignores LLM_GPU_LAYERS; point at the GPU rebuild instructions.
if command -v nvidia-smi > /dev/null 2>&1; then
    echo "note: NVIDIA GPU detected - the default llama-cpp-python build is CPU-only. To offload inference to the GPU, install a CUDA-enabled build and set LLM_GPU_LAYERS=-1 in .env; see backend/README.md (Install variants)."
fi

# -- [4/5] Frontend install --------------------------------------------------
step "[4/5] Installing frontend dependencies (npm ci)"
(cd "$frontend_dir" && npm ci --no-fund --no-audit) \
    || fail "npm ci failed (see output above). Fix the reported issue and re-run."
echo "Frontend dependencies installed."

# -- [5/5] .env --------------------------------------------------------------
step "[5/5] Environment file"
if [ -f "$repo_root/.env" ]; then
    echo ".env already exists - leaving it untouched."
else
    cp "$repo_root/.env.example" "$repo_root/.env"
    echo ".env created from .env.example (defaults are fine for local use)."
fi

printf '\nSetup complete. Next steps (from the repo root):\n'
echo "  1. scripts/download_model.sh     (~2.3 GB, one-time)"
echo "  2. scripts/build_frontend.sh"
echo "  3. cd backend && .venv/bin/uvicorn app.main:app --port 8000"
echo "  4. open http://localhost:8000/"
echo "The audit database (data/lunablue.db) is created automatically on first start."
