#!/usr/bin/env sh
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

step "[3/5] Installing the LLM runtime (llama-cpp-python)"
# Install llama-cpp-python from a prebuilt wheel index, never from the
# PyPI sdist: a source build needs CMake + a C++ toolchain, and pip may
# prefer a newer sdist over an older wheel without --only-binary.
#
# The wheel tier is picked per machine: nvidia-smi reports the driver's
# maximum supported CUDA version, and app.llm.native.pick_wheel_tier maps
# it to the matching CUDA wheel index (cu130 for 13.0+, cu124 for 12.4+,
# CPU otherwise). The CUDA runtime libraries come from the nvidia-* pip
# packages, so no CUDA toolkit install is required.
tier="cpu"
if command -v nvidia-smi > /dev/null 2>&1; then
    smi_out=$(nvidia-smi 2>/dev/null) || smi_out=""
    if [ -n "$smi_out" ]; then
        tier=$(printf '%s\n' "$smi_out" | "$venv_python" -c \
            "import sys; from app.llm.native import pick_wheel_tier; print(pick_wheel_tier(sys.stdin.read()))" \
            2>/dev/null) || tier="cpu"
        [ -n "$tier" ] || tier="cpu"
    fi
fi

wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cpu"
runtime_pkgs=""
case "$tier" in
    cu130)
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cu130"
        runtime_pkgs="nvidia-cuda-runtime-cu13 nvidia-cublas-cu13"
        echo "NVIDIA driver supports CUDA 13+: selecting the cu130 GPU wheel." ;;
    cu124)
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cu124"
        runtime_pkgs="nvidia-cuda-runtime-cu12 nvidia-cublas-cu12"
        echo "NVIDIA driver supports CUDA 12.4+: selecting the cu124 GPU wheel." ;;
    cpu-old-driver)
        echo "note: NVIDIA GPU found, but its driver is too old for the prebuilt CUDA wheels (they need CUDA 12.4+ driver support). Installing the CPU build; update your driver (https://www.nvidia.com/drivers) and re-run scripts/setup.sh to enable GPU inference." ;;
esac

# Idempotency: skip the install only when the existing build already
# matches intent (probe states: missing / broken / cpu / gpu). Each probe
# runs in a fresh python process - a reinstalled wheel cannot be
# re-imported into a process that already loaded the old one.
state=$("$venv_python" -c "from app.llm.native import probe_install_state; print(probe_install_state())") || state="broken"

gpu_active=0
need_install=1
if [ -n "$runtime_pkgs" ] && [ "$state" = "gpu" ]; then
    echo "llama-cpp-python with GPU offload already installed - leaving it untouched."
    gpu_active=1
    need_install=0
elif [ -z "$runtime_pkgs" ] && { [ "$state" = "gpu" ] || [ "$state" = "cpu" ]; }; then
    echo "llama-cpp-python already installed - leaving it untouched."
    need_install=0
fi

if [ "$need_install" = 1 ]; then
    if [ -n "$runtime_pkgs" ]; then
        # shellcheck disable=SC2086  # word-splitting is intended
        "$venv_python" -m pip install --quiet --only-binary=:all: $runtime_pkgs \
            || fail "installing the NVIDIA CUDA runtime packages ($runtime_pkgs) failed (see pip output above)."
    fi
    "$venv_python" -m pip install --quiet llama-cpp-python --force-reinstall --no-cache-dir --only-binary=:all: \
        --index-url "$wheel_index" \
        --extra-index-url https://pypi.org/simple \
        || fail "llama-cpp-python install failed. Retry the prebuilt wheel directly: backend/.venv/bin/pip install llama-cpp-python --only-binary=:all: --index-url $wheel_index --extra-index-url https://pypi.org/simple. Building from source instead needs CMake and a C++ toolchain (build-essential + cmake on Debian/Ubuntu, Xcode CLT on macOS) - see backend/README.md (Install variants), incl. GPU builds."
    if [ -n "$runtime_pkgs" ]; then
        # Verify the GPU wheel actually initializes here; if not, fall back
        # to the CPU wheel so setup still ends in a working state.
        state=$("$venv_python" -c "from app.llm.native import probe_install_state; print(probe_install_state())") || state="broken"
        if [ "$state" = "gpu" ]; then
            gpu_active=1
            echo "GPU build verified: llama.cpp reports GPU offload support."
        else
            echo "warning: the $tier GPU wheel did not initialize on this machine - falling back to the CPU build. Update your NVIDIA driver and re-run setup to retry GPU."
            "$venv_python" -m pip install --quiet llama-cpp-python --force-reinstall --no-cache-dir --only-binary=:all: \
                --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
                --extra-index-url https://pypi.org/simple \
                || fail "CPU fallback install failed (see pip output above)."
        fi
    fi
fi
"$venv_python" -m pip install --quiet -e "$backend_dir[dev,llm]" \
    || fail "backend[dev,llm] install failed (see pip output above). Fix the reported issue and re-run."
if [ "$gpu_active" = 1 ]; then
    echo "LLM runtime installed (GPU-accelerated, $tier)."
else
    echo "LLM runtime installed (CPU)."
fi

# -- [4/5] Frontend install --------------------------------------------------
step "[4/5] Installing frontend dependencies (npm ci)"
(cd "$frontend_dir" && npm ci --no-fund --no-audit) \
    || fail "npm ci failed (see output above). Fix the reported issue and re-run."
echo "Frontend dependencies installed."

# -- [5/5] .env --------------------------------------------------------------
step "[5/5] Environment file"
env_file="$repo_root/.env"
if [ -f "$env_file" ]; then
    echo ".env already exists - leaving it untouched."
else
    cp "$repo_root/.env.example" "$env_file"
    echo ".env created from .env.example (defaults are fine for local use)."
fi

# A verified GPU build defaults to full offload. Only the absent/0 cases
# are touched - any other explicit LLM_GPU_LAYERS value is the user's.
if [ "$gpu_active" = 1 ]; then
    if ! grep -q '^[[:space:]]*LLM_GPU_LAYERS[[:space:]]*=' "$env_file"; then
        printf 'LLM_GPU_LAYERS=-1\n' >> "$env_file"
        echo "LLM_GPU_LAYERS=-1 appended to .env (offload all layers to the GPU)."
    elif grep -q '^[[:space:]]*LLM_GPU_LAYERS[[:space:]]*=[[:space:]]*0[[:space:]]*$' "$env_file"; then
        sed 's/^[[:space:]]*LLM_GPU_LAYERS[[:space:]]*=[[:space:]]*0[[:space:]]*$/LLM_GPU_LAYERS=-1/' "$env_file" > "$env_file.tmp" \
            && mv "$env_file.tmp" "$env_file"
        echo "LLM_GPU_LAYERS changed 0 -> -1 in .env (offload all layers to the GPU)."
    else
        echo ".env keeps your existing LLM_GPU_LAYERS value."
    fi
fi

if [ "$gpu_active" = 1 ]; then
    printf '\nLLM inference: GPU (%s wheel, CUDA runtime from pip).\n' "$tier"
else
    printf '\nLLM inference: CPU.\n'
fi
printf 'Setup complete. Next steps (from the repo root):\n'
echo "  1. scripts/download_model.sh     (~2.3 GB, one-time)"
echo "  2. scripts/build_frontend.sh"
echo "  3. cd backend && .venv/bin/uvicorn app.main:app --port 8000"
echo "  4. open http://localhost:8000/"
echo "The audit database (data/lunablue.db) is created automatically on first start."
