# LunaBlue

LunaBlue is a local-first AI assistant that runs entirely on your own machine: a single Python FastAPI process serves the React UI, runs LangGraph orchestration, and executes an in-process `llama-cpp-python` LLM. Runtime state lives in memory and streams to the UI over WebSockets, while a full audit trail of prompts, responses, and governance decisions is persisted to a local SQLite database — no remote model servers, no database server, no data leaving your hardware.

## Prerequisites

- **Python 3.11+**
- **Node.js 20+** (22 LTS recommended)

That's all — `scripts/setup` checks each one and tells you what to fix if it's missing. The audit database is a local SQLite file created automatically on first start; nothing to install or run.

## Quickstart

From a fresh clone, run (use the `.ps1` scripts on Windows, `.sh` on macOS/Linux):

```
scripts/setup.ps1                  # 1. venv + backend + frontend deps + .env  (~3-4 min)
scripts/download_model.ps1         # 2. fetch the default model (~2.3 GB, one-time)
scripts/build_frontend.ps1         # 3. build the UI into the backend
```

Then start the service and open <http://localhost:8000/>:

```
cd backend
.venv\Scripts\uvicorn app.main:app --port 8000     # Windows
.venv/bin/uvicorn app.main:app --port 8000         # macOS/Linux
```

On first start the backend creates the audit database at `data/lunablue.db` and applies the schema automatically. One FastAPI process now serves both the chat UI and the API. Submit a prompt, watch the live phases stream in, and ask for research to see a background agent appear in the Agents panel. Verify the service with `curl http://localhost:8000/api/health` — it reports `{"service":"lunablue","version":"1.0.0","status":"ok"}` — and per-dependency readiness with `curl http://localhost:8000/api/health/ready`.

Every script is idempotent and safe to re-run. Configuration lives in `.env` (created from [.env.example](.env.example) by setup); the defaults work out of the box. For frontend development with hot reload, use the Vite dev server instead: see [frontend/README.md](frontend/README.md). For GPU builds of the LLM runtime, see [backend/README.md](backend/README.md).

## Documentation

- [docs/Architecture.md](docs/Architecture.md) — full system architecture, directory structure, and design principles.
- [docs/BuildPlan.md](docs/BuildPlan.md) — the 18-step incremental plan the solution was built by.
- [docs/Components/](docs/Components/) — component deep-dives: the FastAPI service, the React frontend, the SQLite audit store.
- [docs/DataRetention.md](docs/DataRetention.md) — audit redaction and retention windows.
- [CHANGELOG.md](CHANGELOG.md) — what shipped in v1.0.

## Testing

Both suites run on any machine without a GPU, a model file, or manual setup —
the LLM runtime is faked; everything else is exercised for real.

**Backend** (`tests/backend/`, run from the repo root):

```
pip install -e backend[dev]
pytest
```

Database-backed tests (audit persistence, migration parity) run against a
per-session temp-file SQLite database automatically — nothing to start, and
nothing skips.

**Frontend** (`frontend/tests/`, Vitest + React Testing Library):

```
cd frontend
npm install
npm test        # or: npm run test:watch
```

CI (`.github/workflows/ci.yml`) runs ruff + the backend suite and the
frontend type-check + build + tests on every push — no database service
required.

## v1.0 capabilities

- **Local-first chat** with an in-process `llama.cpp` model (default: Phi-3-mini, CPU-only; GPU offload configurable) — prompts and answers never leave the machine.
- **Governed, fully audited prompt lifecycle:** every prompt is normalized, policy-tagged, and reviewed; raw prompt, reviewed prompt, response, and governance metadata all land in the local SQLite audit database, with optional secret/PII redaction and retention windows ([docs/DataRetention.md](docs/DataRetention.md)).
- **LangGraph orchestration:** prompt engineering → LLM review → agent spawn → respond, executed as a graph in the same process.
- **Live WebSocket state:** run phases, agent lifecycle events, and readiness stream to the UI in real time, with an automatic polling fallback.
- **Background agents with UI visibility:** prompts can spawn agents (e.g. research) that keep working after the answer returns; the AgentPanel shows their state, events, and results live.
- **Hardened failure behavior:** fail-fast startup validation, a `{code, message, request_id, detail}` error taxonomy, generation timeouts, a busy guard, WebSocket heartbeats, and per-dependency readiness (`/api/health/ready`) — model crashes and database outages degrade cleanly and recover.

**Known limitations:** single-node and single-process by design; one model loaded at a time, and generations execute serially on it (the busy guard sheds load beyond a small queue rather than scaling out); session state is in-memory, so a restart clears live sessions (the audit trail in `data/lunablue.db` survives); no authentication — it binds to `127.0.0.1` for one local user.
