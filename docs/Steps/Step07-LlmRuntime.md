# Step 7 Prompt — Bring Up the Local LLM Runtime

Use this prompt to execute Step 7 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/API.md`). Steps 1–6 delivered a FastAPI service with Postgres audit and governance intake; `POST /api/prompt` still returns a stubbed response. This step brings up the real model.

## Objective

Implement the in-process local LLM runtime: a **single global** `llama-cpp-python` instance created once at startup and shared by all execution paths, plus the tooling to fetch a model file. This is the architecture's core design principle — in-process execution, no external model server.

## Tasks

1. Add `llama-cpp-python` to `backend/pyproject.toml`. Document (in `backend/README.md` or the root README) the install variants: CPU-only default, and the environment flags for CUDA / Metal / ROCm builds.
2. Implement `backend/app/llm/runtime.py`:
   - A `LlamaRuntime` class wrapping `llama_cpp.Llama`, configured from settings: `model_path`, `llm_context_size`, `llm_gpu_layers`, plus sensible generation defaults (max tokens, temperature) overridable per call.
   - Constructed **once** in the `main.py` lifespan handler after config validation; fail fast with a clear error if the model file is missing (point the user to `scripts/download_model`).
   - An async `generate(prompt, *, system=None, **overrides) -> GenerationResult` method. `llama.cpp` inference is blocking and not concurrency-safe: serialize access with an `asyncio.Lock` (or single-worker queue) and run inference in a thread executor so the event loop never blocks.
   - `GenerationResult` carries the text plus metadata: model id, token counts, and duration — the audit layer (Step 8) will persist these.
   - Expose the runtime via dependency injection; add a `loaded` / model-info property for health checks.
3. Create `backend/app/llm/prompts/` with an initial system prompt template file for the assistant persona (used properly in Step 9; keep it minimal now).
4. Create `scripts/download_model.ps1` and `scripts/download_model.sh` that fetch a documented default GGUF model (choose a small, permissively licensed instruct model that runs on CPU, e.g. a 3B–8B quantized build) into `models/`, with the target filename matching `.env.example`'s `MODEL_PATH` default. Update `models/README.md` with the model choice, license note, and how to substitute another GGUF.
5. Extend the readiness check to report whether the model is loaded, and add a temporary debug route or test hook that runs a direct `generate()` call.

## Constraints

- Nothing outside `llm/` may import `llama_cpp` — the single-global-instance rule from `docs/Architecture.md` must stay enforceable.
- Startup must not silently download models; fetching is an explicit script action.
- The event loop must remain responsive during generation (health endpoint answers while a completion runs).

## Verification

- `scripts/download_model` places the GGUF file in `models/` and the service then starts, logging model load with its parameters.
- A debug/test generation call returns coherent model output with populated token/duration metadata.
- `GET /api/health` responds promptly *while* a generation is in progress.
- Starting the service without a model file fails fast with an actionable error message.
- Two concurrent generation calls serialize correctly (no crash, both complete).
