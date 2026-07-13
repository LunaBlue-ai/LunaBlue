# Step 5 Prompt — Expose the Prompt API

Use this prompt to execute Step 5 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/API.md`). Steps 1–4 delivered a runnable FastAPI service with Postgres, Alembic migrations, and an `AuditService` that records structured events off the hot path via dependency injection.

## Objective

Expose the prompt submission API with typed schemas and a **stubbed** response. Every request is assigned an id and audited. The LLM does not exist yet (Step 7) — this step proves the API contract and the audit flow.

## Tasks

1. Implement `backend/app/api/schemas/prompt.py` with Pydantic models:
   - `PromptRequest`: `text` (required, non-empty, bounded length), optional `session_id`, optional `user_id`, optional `metadata` dict.
   - `PromptResponse`: `request_id`, `session_id`, `status` (e.g. `completed` / `failed`), `response_text`, `created_at`.
   - Design these as the stable public contract — the frontend (Step 11) will mirror them in TypeScript.
2. Implement `backend/app/api/routes/prompt.py`:
   - `POST /api/prompt` accepting `PromptRequest`.
   - Generate a UUID `request_id`; create or resolve the session (emit a `SessionEvent` for new sessions).
   - Emit a `PromptRequestEvent` with the raw prompt text (reviewed prompt stays null until Step 6).
   - Return a `PromptResponse` with a clearly canned `response_text` (e.g. echoing the prompt with a "stub" marker) and `status="completed"`.
   - Validation errors return 422 with helpful messages; oversized prompts are rejected, not truncated.
3. Register the route in the router aggregator under `/api`.
4. Update the OpenAPI metadata (summary, description, response models) so `/docs` renders a usable contract.

## Constraints

- Route handlers do orchestration-free work only: validate, delegate, respond (per `docs/Components/API.md` — `api/` is routing only). Keep the handler thin so Steps 6–9 can slot governance and the graph underneath without rewriting the route.
- No direct DB access from the route — all persistence goes through `AuditService`.
- The response shape defined here should survive Steps 8–9 unchanged; only `response_text` content will change from canned to real.

## Verification

- `curl -X POST http://localhost:8000/api/prompt -H "Content-Type: application/json" -d '{"text": "hello"}'` returns 200 with a well-formed `PromptResponse` including a UUID `request_id`.
- The corresponding row appears in `prompt_requests` with the raw prompt text and timestamp.
- Submitting an empty or oversized prompt returns 422 and writes no audit row (or writes a rejected-request row — choose and document).
- `/docs` shows the endpoint with complete request/response schemas.
