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
