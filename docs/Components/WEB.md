# Web React

## Purpose

The Web React frontend is the user-facing companion for LunaBlue. It runs as a static app served by FastAPI and communicates with the backend through HTTP APIs and optional WebSockets for live updates.

## Responsibilities

- collect user prompt input and submit it to the backend
- display initial prompt responses and final assistant output
- render agent lifecycle and status information
- show live updates from shared runtime state using WebSockets
- present backend connectivity and session status

## Directory Mapping

This component lives under `frontend/` in the repository layout defined in [Architecture.md](../Architecture.md#directory-structure):

- `vite.config.ts` — Vite build, with output wired (or copied by `scripts/build_frontend`) into `backend/app/static`.
- `src/api/` — `client.ts` (HTTP client for `/api/prompt` and agent status), `ws.ts` (WebSocket connection with polling fallback).
- `src/components/` — `Chat/` (prompt input, message list, live run phases), `AgentPanel/` (agent list, states, expandable event detail), `StatusBar/` (backend connectivity, live channel, model/readiness status, active-agent count, session id, backend version).
- `src/hooks/` — `useWebSocket` (socket lifecycle + polling fallback), `usePromptSubmit`.
- `src/state/` — React context + reducer (`AppState.tsx`) for prompts, agents, and live progress.
- `src/types/` — shared TypeScript types mirroring the backend Pydantic schemas.
- `tests/` — Vitest + React Testing Library suites (`npm test`).

## Build Approach

1. Scaffold a React app with Vite under `frontend/`.
2. Build a chat-style UI (`src/components/Chat/`) that submits prompts to `/api/prompt`.
3. Add support for WebSocket connections (`src/api/ws.ts`) to receive state and agent status updates.
4. Implement an API client layer (`src/api/client.ts`) for prompt submission and agent status polling.
5. Manage frontend state for active prompts, agent IDs, and live progress in `src/state/`.
6. Keep UI logic separate from backend orchestration and model execution.

## Implementation Notes

- Use React hooks and context for state management.
- Develop against the Vite dev server, proxying `/api` and `/ws` to FastAPI; for deployment, `scripts/build_frontend` copies the production bundle into `backend/app/static` (a gitignored build artifact), which FastAPI mounts so the app is served from the same service.
- Support optional polling fallback for environments where WebSockets are unavailable.
- Display agent IDs, queue status, and last result values.
- Expose feedback and session controls without embedding model logic in the browser.
