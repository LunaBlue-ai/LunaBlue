# Step 9 Prompt — Introduce the LangGraph Main Graph

Use this prompt to execute Step 9 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/API.md`). Steps 1–8 delivered a working end-to-end loop: `POST /api/prompt` → governance → `LlamaRuntime.generate()` → audited response, behind a pipeline seam that isolates the route from the flow's internals.

## Objective

Replace the direct LLM call with a **LangGraph main request graph** — the orchestration backbone. External behavior stays identical; internally, the prompt now flows through explicit, auditable graph nodes: prompt engineering → LLM review → response synthesis (with an agent-spawn node arriving in Step 14).

## Tasks

1. Add `langgraph` to `backend/pyproject.toml`.
2. Define the graph state schema in `backend/app/orchestration/graph.py`: a typed state (TypedDict or Pydantic) carrying request id, session id, reviewed prompt, governance metadata, engineered prompt, review outcome, draft output, final output, and accumulated decision metadata.
3. Implement the nodes in `backend/app/orchestration/nodes/`:
   - `prompt_engineering.py` — transforms the reviewed prompt into the engineered generation input: selects and fills the system template from `llm/prompts/`, applies governance safety directives, and records what it did in decision metadata.
   - `llm_review.py` — an LLM-assisted review/planning pass over the engineered prompt (e.g. classify intent, decide whether background work is warranted, flag concerns). Its judgment lands in the graph state and decision metadata; keep the prompt for it in `llm/prompts/`.
   - `respond.py` — final response synthesis: produces the answer via `LlamaRuntime`, sets both draft and final output.
4. Assemble the graph in `graph.py` (prompt_engineering → llm_review → respond, with room for a conditional agent-spawn edge in Step 14) and compile it once at startup.
5. Replace the Step 8 pipeline internals with graph invocation. The route and API contract do not change. The `PromptResponseEvent` now also carries the accumulated decision metadata (engineered prompt summary, review outcome, node timings) in its governance/metadata fields.
6. All model calls inside nodes go through the injected `LlamaRuntime` — nodes never construct or import `llama_cpp` directly.

## Constraints

- `orchestration/` owns graphs and nodes; `api/` remains routing-only; only `llm/` touches llama.cpp (per `docs/Architecture.md`).
- Nodes must be individually testable: pure functions of (state, injected dependencies) — no module-level singletons.
- Prompt templates live in `llm/prompts/`, not inline in node code.
- Same public behavior: response schema, latency profile (two LLM calls now — review + respond — is acceptable; document it), and error handling from Step 8 all hold.

## Verification

- The same API call from Step 8 returns an equivalent-quality answer, now produced by the graph.
- The audit trail for a request shows decision metadata from every node: engineering transformations, review outcome, and synthesis details.
- Unit-style test: each node runs against a fake LLM runtime and a hand-built state, producing the expected state transitions.
- A generation failure inside any node surfaces as the same clean failure behavior established in Step 8.
