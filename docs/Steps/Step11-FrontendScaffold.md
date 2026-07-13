# Step 11 Prompt — Scaffold the React Frontend

Use this prompt to execute Step 11 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/WEB.md`). The backend (Steps 1–10) serves `POST /api/prompt`, `GET /api/runs/{id}`, `GET /api/sessions/{id}`, and health checks. The `frontend/` directory is empty.

## Objective

Scaffold the React frontend with Vite and TypeScript: a chat-style UI that submits prompts and renders responses, developed against the Vite dev server proxying to FastAPI. WebSockets come in Step 13; agent panels in Step 15.

## Tasks

1. Scaffold a Vite + React + TypeScript app in `frontend/` following the layout in `docs/Architecture.md`: `src/api/`, `src/components/`, `src/hooks/`, `src/state/`, `src/types/`.
2. Implement `src/types/` mirroring the backend Pydantic schemas: `PromptRequest`, `PromptResponse`, run status, and session types. Keep names and fields aligned with `api/schemas/` — these are the single source of truth on the frontend.
3. Implement `src/api/client.ts`: a thin typed HTTP client with `submitPrompt()`, `getRun()`, `getSession()`, `getHealth()`; base-path aware (same-origin `/api`), with basic error normalization (network vs. HTTP error vs. validation detail).
4. Implement frontend state in `src/state/`: React context + reducer holding the session id, message list (user prompts and assistant responses, with pending/completed/failed status per message), and backend connectivity status.
5. Implement `src/components/Chat/`: message list with clear user/assistant styling, a prompt input with submit-on-Enter, a pending indicator while a request is in flight, and inline error display for failed prompts. Wire it via a `usePromptSubmit` hook in `src/hooks/`.
6. Configure `vite.config.ts` to proxy `/api` (and `/ws`, for Step 13) to `http://localhost:8000` in dev, and set `build.outDir` (or leave default `dist/` — Step 12's script copies it).
7. Add `npm run dev`, `build`, and `preview` scripts; document the dev workflow (backend on :8000, `npm run dev` for the UI) in `frontend/README.md`.

## Constraints

- No backend logic in the browser: the UI submits prompts and renders results/status only (per `docs/Components/WEB.md`).
- Use React hooks and context for state — no heavyweight state library.
- All backend communication goes through `src/api/client.ts`; components never call `fetch` directly.
- Keep the visual layer simple and clean; polish is not this step's goal, structure is.

## Verification

- With the backend running and `npm run dev`, a user can open the app, type a prompt, and see the model's real answer appear in the chat.
- A failed request (e.g. backend stopped) shows a clear inline error and the UI stays usable.
- The pending state renders while generation runs.
- `npm run build` completes without type errors.
