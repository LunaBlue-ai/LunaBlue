# LunaBlue Frontend

React + Vite + TypeScript chat UI for LunaBlue (see
[docs/Components/WEB.md](../docs/Components/WEB.md)). It submits prompts to
the FastAPI backend, renders responses with live run phases over WebSockets,
and shows background agents in a live panel.

## Development workflow

Two processes side by side:

1. **Backend** on `http://localhost:8000` (from `backend/`, with the model
   downloaded and Postgres up — see the root README):

   ```powershell
   uvicorn app.main:app --port 8000
   ```

2. **Frontend** dev server (from `frontend/`):

   ```powershell
   npm install   # first time only
   npm run dev
   ```

Open the printed URL (default `http://localhost:5173`). The dev server
proxies `/api` and `/ws` to the backend (`vite.config.ts`), so the app talks
to it same-origin with no CORS configuration.

## Scripts

| Command           | What it does                                          |
| ----------------- | ----------------------------------------------------- |
| `npm run dev`     | Vite dev server with `/api` + `/ws` proxy to `:8000`  |
| `npm run build`   | Type-check (`tsc -b`) and build production bundle to `dist/` |
| `npm run preview` | Serve the production build locally                    |

For deployment, `scripts/build_frontend` copies `dist/` into
`backend/app/static` (Step 12), which FastAPI serves.

## Layout

- `src/api/client.ts` — the only module that makes HTTP calls; typed
  wrappers for `POST /api/prompt`, run/session status, agents, health, and
  readiness, with errors normalized to `ApiError`
  (`network` / `http` / `validation`).
- `src/api/ws.ts` — the `/ws` WebSocket connection with reconnect;
  `src/hooks/useWebSocket.ts` wires it (and the polling fallback) to state.
- `src/types/` — TypeScript mirrors of the backend Pydantic schemas in
  `backend/app/api/schemas/` (the single source of truth).
- `src/state/` — React context + reducer: session id, message list with
  per-message status and live phase, connectivity, agents, readiness.
- `src/hooks/usePromptSubmit.ts` — submission flow wiring state to the client.
- `src/components/Chat/` — message list, prompt input (Enter to send,
  Shift+Enter for a newline), live phase indicator, inline errors.
- `src/components/AgentPanel/` — background agents with expandable event
  detail.
- `src/components/StatusBar/` — connectivity, live channel, model/readiness
  status, active-agent count, session id, and backend version.
- `tests/` — Vitest + React Testing Library suites (`npm test`).
