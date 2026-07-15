# LunaBlue Frontend

React + Vite + TypeScript chat UI for LunaBlue (see
[docs/Components/WEB.md](../docs/Components/WEB.md)). It submits prompts to
the FastAPI backend and renders responses; WebSocket live updates arrive in
Step 13 and agent panels in Step 15.

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

- `src/api/client.ts` — the only module that calls the backend; typed
  wrappers for `POST /api/prompt`, `GET /api/runs/{id}`,
  `GET /api/sessions/{id}`, and `GET /api/health`, with errors normalized to
  `ApiError` (`network` / `http` / `validation`).
- `src/types/` — TypeScript mirrors of the backend Pydantic schemas in
  `backend/app/api/schemas/` (the single source of truth).
- `src/state/` — React context + reducer: session id, message list with
  per-message pending/completed/failed status, backend connectivity.
- `src/hooks/usePromptSubmit.ts` — submission flow wiring state to the client.
- `src/components/Chat/` — message list, prompt input (Enter to send,
  Shift+Enter for a newline), pending indicator, inline errors.
- `src/components/StatusBar/` — backend connectivity and session id.
