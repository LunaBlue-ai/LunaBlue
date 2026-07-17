# LunaBlue Backend

FastAPI service hosting the LunaBlue UI, APIs, LangGraph orchestration, and the local LLM. See [docs/Architecture.md](../docs/Architecture.md) and [docs/Components/API.md](../docs/Components/API.md).

## Setup

From the repository root:

```bash
python -m venv backend/.venv
backend/.venv/Scripts/activate      # Windows; on Unix: source backend/.venv/bin/activate
pip install -e "backend[dev,llm]"
```

The `llm` extra pulls in `llama-cpp-python`, which the real server needs but
tests never do (Step 16): `pip install -e "backend[dev]"` is enough to run
`pytest` from the repo root.

Configuration is read from environment variables and the repo-root `.env` (copy `.env.example` to `.env` and adjust). All settings are defined in [app/config.py](app/config.py).

## LLM runtime (`llama-cpp-python`)

The backend runs the model in-process via `llama-cpp-python`. Fetch the default model first (see [models/README.md](../models/README.md)):

```bash
scripts/download_model.ps1     # Windows
scripts/download_model.sh      # Unix / macOS
```

### Install variants

`scripts/setup` installs the **prebuilt CPU wheel** of `llama-cpp-python` from the project's wheel index (`--only-binary=:all: --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --extra-index-url https://pypi.org/simple`) — no toolchain needed, works everywhere. A bare `pip install -e "backend[dev,llm]"` may instead resolve to the PyPI **sdist** and build from source; on Windows that needs CMake + Visual Studio Build Tools **and** long paths enabled — an `OSError: [Errno 2] No such file or directory` on a deep `...\vendor\llama.cpp\...` path during install is the long-path (260-char `MAX_PATH`) symptom, not a missing file. Prefer the wheel-index command above; enabling `LongPathsEnabled=1` in the registry is only needed if you genuinely want a source build.

To offload layers to a GPU (`LLM_GPU_LAYERS` > 0), reinstall `llama-cpp-python` with the matching backend enabled at build time:

```bash
# CUDA (NVIDIA)
CMAKE_ARGS="-DGGML_CUDA=on" pip install --force-reinstall --no-cache-dir llama-cpp-python

# Metal (Apple Silicon)
CMAKE_ARGS="-DGGML_METAL=on" pip install --force-reinstall --no-cache-dir llama-cpp-python

# ROCm (AMD)
CMAKE_ARGS="-DGGML_HIPBLAS=on" pip install --force-reinstall --no-cache-dir llama-cpp-python
```

On Windows (PowerShell) set the variable first: `$env:CMAKE_ARGS = "-DGGML_CUDA=on"`. Source builds need CMake and a C++ toolchain (plus the CUDA/ROCm SDK for those variants).

Prebuilt CUDA wheels avoid the toolchain entirely. Two things must line up: the wheel's CUDA series must match the CUDA runtime installed on the machine (check `nvidia-smi` / `$env:CUDA_PATH` — a `cu124` wheel needs the 12.x runtime DLLs, `cu130` the 13.x ones), and pip needs the wheel index for `llama-cpp-python` itself plus PyPI for its dependencies:

```powershell
pip install llama-cpp-python --force-reinstall --no-cache-dir --only-binary=:all: `
    --index-url https://abetlen.github.io/llama-cpp-python/whl/cu130 `
    --extra-index-url https://pypi.org/simple
```

(`--only-binary=:all:` stops pip from "helpfully" falling back to a CPU source build. Verify with `python -c "import llama_cpp; print(llama_cpp.llama_supports_gpu_offload())"`.)

The runtime probes this at startup: requesting `LLM_GPU_LAYERS` != 0 on a CPU-only build logs a warning (llama.cpp would otherwise silently run on CPU), and `/api/health/ready` reports the capability as `gpu_offload_supported` in the model check.

## Run

From `backend/`:

```bash
uvicorn app.main:app --reload
```

Then verify:

```bash
curl http://localhost:8000/api/health
```

Expected response: `{"service":"lunablue","version":"1.0.0","status":"ok"}`

`/api/health` is liveness only (the process is up). Dependency readiness —
database reachable, model loaded and healthy, audit queue not overflowing,
agent runner alive — is reported per-check by:

```bash
curl http://localhost:8000/api/health/ready
```

which answers 503 (same body shape, with a `checks` breakdown) while any
dependency is degraded. Startup fails fast: invalid settings (missing model
file, malformed `DATABASE_URL`, out-of-range limits, bad redaction regexes)
abort boot with one aggregated, actionable message.

## Operations

- **Error shape:** every non-2xx API response carries
  `{code, message, request_id, detail}`; the `X-Request-ID` header correlates
  responses with server logs. See `docs/Components/API.md` (Hardening).
- **Audit retention & redaction:** `scripts/retention[.ps1|.sh] [--dry-run]`
  deletes audit rows older than the configured window
  (`AUDIT_RETENTION_DAYS`); `AUDIT_REDACTION_ENABLED=true` masks secrets/PII
  before audit rows are written. Both are documented in
  [docs/DataRetention.md](../docs/DataRetention.md).
