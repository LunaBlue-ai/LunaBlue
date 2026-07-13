# Step 8 Prompt — Close the First End-to-End Loop

Use this prompt to execute Step 8 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md`). Steps 1–7 delivered: FastAPI service, Postgres audit (`AuditService`), governance intake (`PromptIntake` / `PolicyEngine`), and a loaded `LlamaRuntime` with async `generate()`. `POST /api/prompt` still returns a canned response.

## Objective

Wire the full minimal vertical slice: **prompt in → governance → local LLM → response out**, with the complete audit chain persisted. This is the pivotal milestone — after this step, LunaBlue actually answers.

## Tasks

1. Rework the `POST /api/prompt` flow (keeping the Step 5 response contract unchanged):
   1. Validate the request (existing).
   2. Governance review via `PromptIntake` (existing) — emit `PromptRequestEvent` with raw + reviewed prompt and governance metadata.
   3. Build the generation input from the reviewed prompt: apply the system prompt template from `llm/prompts/` and any safety directives from `GovernanceMetadata`.
   4. Call `LlamaRuntime.generate()`.
   5. Emit a `PromptResponseEvent` carrying the LLM output text, the final output text (identical for now — they diverge when Step 9 adds review/synthesis), model id, and token/duration metadata.
   6. Return the real generated text in `PromptResponse`.
2. Error handling for the new failure mode: if generation fails or exceeds a configured timeout, return a clean 5xx with `status="failed"`, and audit a failed `PromptResponseEvent` with the error summary. The service must remain healthy afterward.
3. Introduce a thin internal seam between the route and this flow (e.g. a `PromptPipeline` or handler function outside `api/`): Step 9 will replace its internals with LangGraph execution, and the route should not change again. Place it where it belongs per the architecture (orchestration-adjacent, not in `api/`).
4. Remove or gate the Step 7 debug generation route.

## Constraints

- The public API contract from Step 5 does not change — only `response_text` becomes real.
- Route handler stays thin: the pipeline seam owns the governance → LLM → audit sequence.
- All audit writes remain off the hot path via `AuditService`; generation metadata must be complete (model id, tokens, duration).

## Verification

- Submitting "What is LunaBlue?" via the API returns a coherent, model-generated answer.
- Postgres shows the complete linked chain for that request id: `prompt_requests` (raw + reviewed + governance) and `prompt_responses` (LLM output, final output, model metadata) with consistent timestamps.
- A forced generation failure (e.g. absurd token limit or induced timeout) returns a clean failure response, audits it, and the next request succeeds.
- The stubbed-response code path is gone.
