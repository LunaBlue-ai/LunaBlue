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

`scripts/setup` picks the right **prebuilt wheel** of `llama-cpp-python` automatically — re-running setup is the fix for most install/GPU problems:

- On NVIDIA machines it reads the driver's maximum supported CUDA version from `nvidia-smi` ("CUDA Version" in the banner) and installs the matching CUDA wheel **plus the CUDA runtime from pip** (`nvidia-cuda-runtime-*`, `nvidia-cublas-*`) — no CUDA toolkit install needed. On a successful GPU install it also sets `LLM_GPU_LAYERS=-1` in `.env` (unless you already customized it).
- Everywhere else (or when the driver is too old) it installs the CPU wheel.
- Broken installs self-repair: setup probes the installed build (`app.llm.native.probe_install_state`) and force-reinstalls when it doesn't match the machine; if a GPU wheel fails to initialize, setup falls back to the CPU wheel with a warning.

| `nvidia-smi` "CUDA Version" | driver (approx.) | wheel index | CUDA runtime packages |
|---|---|---|---|
| >= 13.0 | 580+ | `whl/cu130` | `nvidia-cuda-runtime-cu13`, `nvidia-cublas-cu13` |
| 12.4 – 12.x | ~551+ | `whl/cu124` | `nvidia-cuda-runtime-cu12`, `nvidia-cublas-cu12` |
| < 12.4 | older | CPU wheel | — (update the driver, then re-run setup) |

All installs use `--only-binary=:all:`: a bare `pip install -e "backend[dev,llm]"` may instead resolve to the PyPI **sdist** and build from source; on Windows that needs CMake + Visual Studio Build Tools **and** long paths enabled — an `OSError: [Errno 2] No such file or directory` on a deep `...\vendor\llama.cpp\...` path during install is the long-path (260-char `MAX_PATH`) symptom, not a missing file. Enabling `LongPathsEnabled=1` in the registry is only needed if you genuinely want a source build.

To install a CUDA tier manually (PowerShell shown; swap `cu124`→`cu130` and `-cu12`→`-cu13` per the table):

```powershell
pip install --only-binary=:all: nvidia-cuda-runtime-cu12 nvidia-cublas-cu12
pip install llama-cpp-python --force-reinstall --no-cache-dir --only-binary=:all: `
    --index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 `
    --extra-index-url https://pypi.org/simple
```

(`--only-binary=:all:` stops pip from "helpfully" falling back to a CPU source build. Verify with `python -c "from app.llm.native import probe_install_state; print(probe_install_state())"` — `gpu` means llama.cpp reports offload support.)

For non-NVIDIA GPUs, build from source with the matching backend enabled (needs CMake + a C++ toolchain, plus the SDK for the variant):

```bash
# Metal (Apple Silicon)
CMAKE_ARGS="-DGGML_METAL=on" pip install --force-reinstall --no-cache-dir llama-cpp-python

# ROCm (AMD)
CMAKE_ARGS="-DGGML_HIPBLAS=on" pip install --force-reinstall --no-cache-dir llama-cpp-python
```

On Windows (PowerShell) set the variable first: `$env:CMAKE_ARGS = "-DGGML_METAL=on"`.

Startup behavior: requesting `LLM_GPU_LAYERS` != 0 on a CPU-only build logs a warning (llama.cpp would otherwise silently run on CPU), and `/api/health/ready` reports the capability as `gpu_offload_supported` in the model check. An installed build that fails to **import** (e.g. a `cu130` wheel on a driver that only supports CUDA 12.x) aborts startup with an actionable `LlamaRuntimeUnavailableError` instead of a raw traceback — re-run `scripts/setup` to repair it.

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
