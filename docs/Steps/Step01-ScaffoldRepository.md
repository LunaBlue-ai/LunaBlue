# Step 1 Prompt — Scaffold the Repository

Use this prompt to execute Step 1 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue**, a local-first AI assistant: a single Python FastAPI process that serves a React UI, runs LangGraph orchestration, executes an in-process `llama-cpp-python` LLM, keeps runtime state in memory (streamed to the UI over WebSockets), and persists a full audit trail to Postgres. The complete design is in `docs/Architecture.md` and `docs/Components/`.

## Objective

Create the solution repository skeleton exactly matching the directory structure defined in `docs/Architecture.md` (section "Directory structure"). No application logic yet — this step produces the empty, well-organized shell every later step builds into.

## Tasks

1. Initialize a git repository (if not already one) with a `main` branch.
2. Create the full directory tree from the architecture doc:
   - `backend/app/` with subpackages `api/routes/`, `api/schemas/`, `governance/`, `orchestration/nodes/`, `orchestration/agents/`, `llm/prompts/`, `state/`, `audit/`, and `static/`. Add empty `__init__.py` files to every Python package so the tree imports cleanly.
   - `backend/migrations/versions/` for Alembic.
   - `frontend/` (empty for now — scaffolded in Step 11).
   - `models/` with a `README.md` explaining that GGUF model files live here, are gitignored, and are fetched by `scripts/download_model` (Step 7).
   - `docs/` — copy the LunaBlue documentation set (Architecture.md, BuildPlan.md, Components/, Steps/) into it.
   - `tests/backend/` and `tests/frontend/`.
   - `scripts/`.
3. Create `.gitignore` covering: Python (`__pycache__/`, `.venv/`, `*.egg-info/`), Node (`node_modules/`, `frontend/dist/`), build artifacts (`backend/app/static/*` except a `.gitkeep`), model files (`models/*.gguf`, `models/*.bin`), environment files (`.env`), and IDE/OS noise.
4. Create `.env.example` documenting every planned environment variable with comments and safe defaults: `DATABASE_URL` (Postgres DSN), `MODEL_PATH`, `LLM_CONTEXT_SIZE`, `LLM_GPU_LAYERS`, `HOST`, `PORT`, `WS_ENABLED`, `GOVERNANCE_STRICT_MODE`, `LOG_LEVEL`.
5. Create `docker-compose.yml` with a `postgres` service (pinned major version, named volume, healthcheck, credentials sourced from `.env`) and an optional commented-out `pgadmin` service.
6. Create a root `README.md` stub: one-paragraph project description, link to `docs/Architecture.md` and `docs/BuildPlan.md`, and a placeholder "Getting started" section to be completed in Step 18.

## Constraints

- Follow the directory structure in `docs/Architecture.md` exactly; do not invent additional top-level folders.
- Do not add application code, dependencies, or configuration beyond what is listed — later steps own those.

## Verification

- `git status` shows a clean, committed tree.
- The directory listing matches the structure in `docs/Architecture.md`.
- `docker compose up -d postgres` starts Postgres successfully using values from a `.env` copied from `.env.example`.
- `python -c "import backend.app"` (or equivalent with the chosen path setup) raises no import errors.
