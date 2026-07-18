# Step 19 Prompt — Closed-Loop Prompt Processing

Use this prompt to execute Step 19 (post-v1.0).

---

You are extending **LunaBlue** (see `docs/Architecture.md` and `docs/Components/API.md`). v1.0 delivered the full loop: `POST /api/prompt` → governance → main graph (`prompt_engineering → llm_review → respond`) → audited response, with every prompt generated in isolation — no prior-turn context ever reaches the LLM.

## Objective

Add the closed-loop prompt-processing cycle: every turn flows **raw prompt → LLM-enhanced prompt → inject rolling chat summary → generate → update summary in the background**. Both artifacts are strictly internal — the user only ever sees the raw prompt and the final response; the enhanced prompt and the summary must never appear in any API response, WebSocket frame, or UI content.

## Tasks

1. **Prompt enhancement node** (`orchestration/nodes/prompt_enhancement.py`): after `prompt_engineering`, the local LLM rewrites the engineered prompt into a clearer, more complete form (`llm/prompts/enhance.md`; instructions in the user turn, per the `llm_review` finding that small local models answer system-role instructions). Enhancement failure never fails the run: fall back to the unenhanced prompt and record the failure in the node's decision record. The enhanced prompt is audited via the decision record inside `prompt_responses.usage["decisions"]` — no schema migration.
2. **Rolling chat summary** per session, capped at `SESSION_SUMMARY_MAX_CHARS` (default 2000):
   - Stored in-memory on the `StateStore` session record, **excluded from `SessionSnapshot`** so it is structurally absent from every wire payload. Reads via `get_session_summary`, writes via `set_session_summary` (no event emitted).
   - Injected by the pipeline into the graph state; the enhancement node appends it under a `### Chat Summary` heading **after** the enhancement LLM call, so the enhancer never sees the summary block.
   - Updated after each successful run by `orchestration/summarizer.py` (`SessionSummarizer`): a fire-and-forget background LLM call (`llm/prompts/summarize_session.md`, background priority) folds the **raw** user prompt plus a response excerpt into the summary. Per-session updates chain in submission order; a failed or empty update keeps the previous summary; hard-truncate overshoot.
3. **Graph wiring**: `START → prompt_engineering → prompt_enhancement → llm_review → … → respond`, with a new `enhancing` run phase between `engineering` and `reviewing`. The node is registered when enhancement *or* the summary is enabled (summary injection lives in it; with enhancement off it runs as a deterministic append); with both off the graph is identical to the v1.0 flow.
4. **Settings** (documented in `.env.example`, bounds-checked in `startup.py`): `PROMPT_ENHANCEMENT_ENABLED` / `PROMPT_ENHANCEMENT_MAX_TOKENS`, `SESSION_SUMMARY_ENABLED` / `SESSION_SUMMARY_MAX_CHARS` / `SESSION_SUMMARY_MAX_TOKENS` — all default on. The lifespan builds the summarizer, passes it to the pipeline, and closes it first on shutdown (pending updates are disposable).
5. **Frontend**: add the `enhancing` phase to `RunPhase` and a "Enhancing the prompt" entry to the `MessageList` phase labels. Nothing else changes client-side.

## Constraints

- Local-first: all enhancement and summarization runs on the single global `LlamaRuntime`; summarize calls use background priority so foreground prompts always win the model.
- Opaque enhancement: the summary lives only behind `get_session_summary` (in-memory, lost on restart by design — the frontend starts a fresh session per page load); the enhanced prompt travels only in graph state and the audited decision record.
- The response latency budget grows by one foreground LLM call (enhance); the summary update adds none.
- Fakes stay deterministic: `make_app`/`make_client` default `summary=False` (the background summarize call would race scripted `queued_responses`); closed-loop tests opt in and synchronize via `SessionSummarizer.wait_idle()`.

## Verification

- Two POSTs with one `session_id`: the second turn's review/respond prompts carry `### Chat Summary` with turn 1's summary; the enhance call never sees it; neither response body, `GET /api/sessions/{id}`, nor any WS frame contains summary text.
- The `prompt_enhancement` decision record (status `enhanced`/`fallback`/`disabled`, the enhanced text, `summary_injected`) lands in `prompt_responses.usage["decisions"]`.
- Enhancement failure degrades gracefully (run completes on the reviewed prompt); a failed summarize call keeps the previous summary and surfaces nowhere.
- With both toggles off, the pipeline behaves exactly as v1.0: two LLM calls, three-node decision list.
