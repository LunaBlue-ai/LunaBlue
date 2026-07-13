# Step 2 Prompt — Stand Up the Backend Skeleton

Use this prompt to execute Step 2 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md`). Step 1 scaffolded the repository: the `backend/app/` package tree, `.env.example`, `docker-compose.yml`, and `.gitignore` all exist.

## Objective

Create a runnable FastAPI service: application factory, typed configuration, and a health endpoint. This is the process that will eventually host everything — frontend, APIs, WebSockets, LangGraph, and the LLM.

## Tasks

1. Create `backend/pyproject.toml` with project metadata and initial dependencies: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`. (Later steps add `sqlalchemy`, `alembic`, `langgraph`, `llama-cpp-python` — do not add them yet.) Include a `dev` extra with `pytest`, `pytest-asyncio`, and `httpx`.
2. Implement `backend/app/config.py` using pydantic-settings:
   - A `Settings` class reading from environment variables / `.env`, with fields matching `.env.example` (`database_url`, `model_path`, `llm_context_size`, `llm_gpu_layers`, `host`, `port`, `ws_enabled`, `governance_strict_mode`, `log_level`).
   - A cached accessor (e.g. `get_settings()`), so settings are loaded once and injectable in tests.
3. Implement `backend/app/main.py`:
   - An application factory `create_app() -> FastAPI` so tests can build isolated instances.
   - An async lifespan context manager. For now it only configures logging from `settings.log_level` and logs startup/shutdown; later steps will add the DB engine (Step 3), the LLM runtime (Step 7), and the state store (Step 10) here — leave clearly marked ordering comments only if genuinely helpful, otherwise keep it clean.
   - Router registration under the `/api` prefix.
   - A module-level `app = create_app()` for uvicorn.
4. Implement `backend/app/api/routes/health.py` with `GET /api/health` returning service name, version, and status. Register it in an `api/routes/__init__.py` router aggregator so future routes plug in the same way.
5. Add a convenience run script or documented command: `uvicorn app.main:app --reload` from `backend/` (document in the backend README or root README).

## Constraints

- `api/` contains routing only — no business logic (per `docs/Components/API.md`).
- All configuration flows through `config.py`; no `os.environ` reads elsewhere.
- Use FastAPI's async support throughout; no synchronous blocking calls in request handlers.

## Verification

- `pip install -e backend[dev]` (or the project's chosen workflow) succeeds.
- The service starts cleanly with uvicorn and logs startup at the configured level.
- `curl http://localhost:8000/api/health` returns HTTP 200 with the expected JSON body.
- `create_app()` can be called twice without side effects (no global state leakage).
