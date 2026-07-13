# LunaBlue Backend

FastAPI service hosting the LunaBlue UI, APIs, LangGraph orchestration, and the local LLM. See [docs/Architecture.md](../docs/Architecture.md) and [docs/Components/API.md](../docs/Components/API.md).

## Setup

From the repository root:

```bash
python -m venv backend/.venv
backend/.venv/Scripts/activate      # Windows; on Unix: source backend/.venv/bin/activate
pip install -e "backend[dev]"
```

Configuration is read from environment variables and the repo-root `.env` (copy `.env.example` to `.env` and adjust). All settings are defined in [app/config.py](app/config.py).

## LLM runtime (`llama-cpp-python`)

The backend runs the model in-process via `llama-cpp-python`. Fetch the default model first (see [models/README.md](../models/README.md)):

```bash
scripts/download_model.ps1     # Windows
scripts/download_model.sh      # Unix / macOS
```

### Install variants

The default `pip install -e "backend[dev]"` builds **CPU-only** — correct and safe everywhere, no extra toolchain needed. To offload layers to a GPU (`LLM_GPU_LAYERS` > 0), reinstall `llama-cpp-python` with the matching backend enabled at build time:

```bash
# CUDA (NVIDIA)
CMAKE_ARGS="-DGGML_CUDA=on" pip install --force-reinstall --no-cache-dir llama-cpp-python

# Metal (Apple Silicon)
CMAKE_ARGS="-DGGML_METAL=on" pip install --force-reinstall --no-cache-dir llama-cpp-python

# ROCm (AMD)
CMAKE_ARGS="-DGGML_HIPBLAS=on" pip install --force-reinstall --no-cache-dir llama-cpp-python
```

On Windows (PowerShell) set the variable first: `$env:CMAKE_ARGS = "-DGGML_CUDA=on"`. Source builds need CMake and a C++ toolchain (plus the CUDA/ROCm SDK for those variants); prebuilt wheels for common configurations are available via the project's wheel index, e.g. `pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124`.

## Run

From `backend/`:

```bash
uvicorn app.main:app --reload
```

Then verify:

```bash
curl http://localhost:8000/api/health
```

Expected response: `{"service":"lunablue","version":"0.1.0","status":"ok"}`
