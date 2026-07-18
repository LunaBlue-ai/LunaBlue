---
name: verify
description: Build, launch, and drive LunaBlue end-to-end to verify a change against the running app.
---

# Verifying LunaBlue

Single FastAPI process serves the React UI, the `/api` routes, and `/ws`.

## Build + launch

```bash
# 1. Build the UI into backend/app/static (from repo root, PowerShell):
scripts/build_frontend.ps1

# 2. Start the backend (venv lives at backend/.venv; model file at models/model.gguf
#    per repo-root .env — startup fails fast if it is missing):
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

Ready when `GET http://127.0.0.1:8000/api/health` returns `{"status": "ok"}`.
Postgres is optional for smoke runs — audit writes are off the hot path and
only log errors. Env vars (e.g. `WS_ENABLED=false`) override repo-root `.env`.

## Driving it

- Prompt flow: `POST /api/prompt` with `{"text": ...}` (synchronous; a real
  CPU model answer takes a few seconds). Live status: `GET /api/runs/{id}`,
  `GET /api/sessions/{id}`.
- WebSocket: connect `ws://127.0.0.1:8000/ws` with the `websockets` package
  (already in backend/.venv). First message is always a `snapshot`
  `{type, seq, ts, payload}`; then `run_updated` events stream each phase
  (received → governance → engineering → reviewing → responding → completed).
  Post a prompt while connected to watch it live.
- The frontend generates its session id client-side and sends it with every
  prompt, so `GET /api/sessions/{id}` 404s until the first run starts —
  that's expected, not a bug.

## Gotchas

- Backend tests must run with `backend/.venv/Scripts/python.exe -m pytest`;
  system python lacks the deps.
- No Playwright in this environment — verify browser-level behavior via the
  wire protocol (real WS/HTTP clients) plus `curl http://127.0.0.1:8000/`
  for bundle serving.
- Kill the uvicorn background task when done; it holds port 8000.
