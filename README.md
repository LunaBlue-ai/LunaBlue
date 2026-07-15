# LunaBlue

LunaBlue is a local-first AI assistant that runs entirely on your own machine: a single Python FastAPI process serves the React UI, runs LangGraph orchestration, and executes an in-process `llama-cpp-python` LLM. Runtime state lives in memory and streams to the UI over WebSockets, while a full audit trail of prompts, responses, and governance decisions is persisted to Postgres — no remote model servers, no data leaving your hardware.

## Documentation

- [docs/Architecture.md](docs/Architecture.md) — full system architecture, directory structure, and design principles.
- [docs/BuildPlan.md](docs/BuildPlan.md) — the 18-step incremental plan for building the solution.

## Getting started

> Full setup (database, model download, configuration) is finalized in Step 18 of the [build plan](docs/BuildPlan.md). The single-process run path already works:

1. Build the frontend into the backend's static directory:

   ```
   scripts/build_frontend.ps1    # Windows
   scripts/build_frontend.sh     # macOS/Linux
   ```

2. Start the backend from `backend/` (requires the model and database from `backend/README.md`):

   ```
   uvicorn app.main:app --port 8000
   ```

3. Open <http://localhost:8000/> — one FastAPI process serves both the chat UI and the API.

For frontend development with hot reload, use the Vite dev server instead: see [frontend/README.md](frontend/README.md).
