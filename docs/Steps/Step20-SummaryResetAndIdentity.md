# Step 20 Prompt — Chat Summary Reset + Persistent Identity Fields

Use this prompt to execute Step 20 (post-v1.0).

---

You are extending **LunaBlue** (see `docs/Architecture.md` and `docs/Components/API.md`). Step 19 delivered closed-loop prompt processing: a per-session rolling chat summary maintained by `SessionSummarizer`, stored on the `StateStore` session record, and injected under a `### Chat Summary` heading by the `prompt_enhancement` node. There is no way to clear stale context, and no notion of stable identity attributes.

## Objective

Let the user clear accumulated conversational context without losing the "minimum viable persona": a **Clear Chat Summary** button wipes the session's rolling buffer, while five **identity fields** — Name, Age, Occupation, Personality, Interests — always persist and keep the local LLM's behavior stable across resets.

## Tasks

1. **Identity store** (`state/identity.py`): the five fields live *outside* the LLM-maintained rolling buffer — `IdentityStore` (env defaults via `IDENTITY_*` settings, runtime full-replace, `format_block()` renders `Label: value` lines omitting empty fields) plus `compose_summary(identity_block, rolling, max_chars)`, which joins the pinned block and the rolling summary under one character budget, truncating only the rolling tail. Because the summarizer never sees the identity block, re-summarization can never drop or distort it — and after a reset the next injection is identity-only, reproducing the required post-reset format with no special casing.
2. **Identity API**: `GET /api/identity` and `PUT /api/identity` (`api/routes/identity.py`, `api/schemas/identity.py`) — one `Identity` schema for both directions, each field capped at 200 characters, PUT is a full replace (omitted fields blank). Runtime edits are in-memory and lost on restart, consistent with live state. Identity fields are user-facing settings; the summary itself stays internal.
3. **Reset endpoint**: `POST /api/sessions/{session_id}/summary/reset` (`api/routes/state.py`) — idempotent 200 with `{session_id, cleared}`; unknown sessions return `cleared=false` without upserting a phantom session (a frontend session doesn't exist server-side until its first prompt).
4. **Epoch guard** (`orchestration/summarizer.py`): a background summarize scheduled before a reset must not finish after it and resurrect the cleared summary. Per-session epoch counter: `schedule()` captures it, `_run()` re-checks it immediately before the store write (the reset can land during the generate await) and discards stale updates; `reset()` bumps the epoch and clears the store. No task cancellation — pending chains settle normally.
5. **Pipeline** (`orchestration/pipeline.py`): the injected `chat_summary` becomes `compose_summary(identity.format_block(), rolling, max_chars=SESSION_SUMMARY_MAX_CHARS)`, still gated with the summary feature (`SESSION_SUMMARY_ENABLED=false` disables both). No change to the graph or the enhancement node.
6. **Frontend**: a slim chat header hosts the low-emphasis **Clear chat summary** button (busy/`Cleared ✓`/retry states; clears internal context, not the visible transcript); an **Identity** panel toggled from the app header edits the five fields (GET on mount, full-replace PUT, `Saved ✓` confirmation).

## Constraints

- Identity is never truncated at injection; the 200-char per-field cap keeps the block far below the summary budget.
- The rolling summary remains invisible to the user; only the identity fields travel on the wire (via `/api/identity`).
- The reset must win every race with in-flight background updates.
- Fakes: `make_app`/`make_client` gain an `identity` knob defaulting to an empty store, so existing exact-content test assertions are untouched.

## Verification

- Two turns with identity set: turn 1 injects the identity-only block; turn 2 injects identity + rolling summary; after `POST .../summary/reset`, turn 3 is identity-only again — asserted on the fake LLM's received prompts end to end.
- A reset issued while a summarize is pending leaves the summary cleared after `wait_idle()`.
- Reset on an unknown session: 200 `cleared=false`, no session created.
- PUT with an over-long field → 422; partial PUT blanks omitted fields.
- Frontend: the button POSTs to the current session's reset endpoint and confirms; the panel loads via GET and saves via full-replace PUT.
