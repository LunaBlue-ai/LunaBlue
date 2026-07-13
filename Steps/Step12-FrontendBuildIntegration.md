# Step 12 Prompt — Integrate the Frontend Build

Use this prompt to execute Step 12 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md`). Steps 1–11 delivered a working backend and a React chat UI that runs against the Vite dev server. The architecture requires a **single self-contained process**: FastAPI serves the built frontend from `backend/app/static/`.

## Objective

Wire the production path: build the React app, place the bundle in `backend/app/static/`, and serve it from FastAPI so one process delivers both the UI and the API.

## Tasks

1. Create `scripts/build_frontend.ps1` and `scripts/build_frontend.sh`:
   - Run `npm ci` (or `npm install` if no lockfile yet) and `npm run build` in `frontend/`.
   - Clear `backend/app/static/` (preserving `.gitkeep`) and copy `frontend/dist/` contents into it.
   - Fail loudly if the build or copy fails.
2. Mount static serving in `main.py`:
   - Serve `backend/app/static/` at the root path, **registered after** all `/api` and `/ws` routes so API routing always wins.
   - SPA fallback: unknown non-`/api` paths return `index.html` (client-side routing safety), while unknown `/api` paths still 404 as JSON.
   - If `static/` is empty (dev mode), the root path returns a helpful JSON or plain-text pointer to the dev workflow instead of erroring.
3. Ensure correct content types and sensible cache headers: hashed assets (`assets/*`) long-cacheable, `index.html` no-cache.
4. Confirm `.gitignore` covers `backend/app/static/*` (build artifact — never committed) and `frontend/dist/`.
5. Update the root README run instructions: `scripts/build_frontend` then start uvicorn → app at `http://localhost:8000/`.

## Constraints

- The dev workflow from Step 11 (Vite dev server + proxy) must keep working unchanged; this step adds the production path, it does not replace dev.
- No web server other than FastAPI/uvicorn — this is the single-process deployment shape from `docs/Architecture.md`.
- The static directory remains a gitignored build artifact.

## Verification

- Run `scripts/build_frontend`, start the backend, open `http://localhost:8000/` — the chat UI loads and works end-to-end from the single process.
- `GET /api/health` still returns JSON (API precedence intact); an unknown `/api/nope` returns a JSON 404, while `/some/client/route` returns the SPA.
- `git status` stays clean after a build (no artifacts tracked).
- With `static/` emptied, the backend still starts and the root path explains the dev workflow.
