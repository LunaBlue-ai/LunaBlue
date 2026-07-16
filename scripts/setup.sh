#!/usr/bin/env sh
# One-shot development setup for LunaBlue (Step 18). Idempotent: safe to
# re-run at any time; each step skips or redoes cleanly.
#   1. Checks prerequisites (Python >= 3.11, Node >= 20, Docker) with
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

command -v docker > /dev/null 2>&1 \
    || fail "Docker not found. Install Docker (https://docs.docker.com/get-docker/) and re-run. LunaBlue uses it for the Postgres audit database (docker compose up -d postgres)."
if docker info > /dev/null 2>&1; then
    echo "Docker $(docker --version | sed 's/Docker version //; s/,.*//')  OK"
else
    echo "warning: Docker CLI found, but the daemon is not running. Setup can continue; start Docker before 'docker compose up -d postgres'."
fi

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

step "[3/5] Installing the LLM runtime (backend[llm]: llama-cpp-python, CPU build)"
if ! "$venv_python" -m pip install --quiet -e "$backend_dir[dev,llm]"; then
    fail "llama-cpp-python install failed. When pip falls back to a source build it needs CMake and a C++ toolchain (build-essential + cmake on Debian/Ubuntu, Xcode CLT on macOS). Install those and re-run, or use the prebuilt wheel index: backend/.venv/bin/pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu - see backend/README.md (Install variants)."
fi
echo "LLM runtime installed."

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
echo "  1. docker compose up -d postgres"
echo "  2. scripts/migrate.sh"
echo "  3. scripts/download_model.sh     (~2.3 GB, one-time)"
echo "  4. scripts/build_frontend.sh"
echo "  5. cd backend && .venv/bin/uvicorn app.main:app --port 8000"
echo "  6. open http://localhost:8000/"
