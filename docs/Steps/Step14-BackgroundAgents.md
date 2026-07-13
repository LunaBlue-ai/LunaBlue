# Step 14 Prompt — Run Background Agents

Use this prompt to execute Step 14 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/API.md`). Steps 1–13 delivered the live single-process app: LangGraph main graph, `StateStore` with an agent registry placeholder, `EventBus` with a defined `agent_updated` event, `agent_events` audit table, and an `llm_review` node that already judges whether background work is warranted.

## Objective

Implement background agents: long-running agent subgraphs spawned by the main graph, executed by a background runner, tracked in shared state, and fully audited. A prompt can now kick off work that continues after its response returns.

## Tasks

1. Implement `backend/app/orchestration/agents/base.py` — the agent lifecycle contract:
   - `AgentSpec`: agent id, kind, originating request/session id, task description, parameters.
   - Lifecycle states: `pending → running → completed | failed | cancelled`, with progress (phase string and/or fraction) and a `last_result` payload.
   - A base class/protocol each agent implements: an async `run(context)` where `context` provides the injected `LlamaRuntime`, `StateStore` handles, and an audit emitter — agents never construct their own dependencies.
2. Implement one concrete first agent as a LangGraph subgraph under `orchestration/agents/` (e.g. a `research` agent that decomposes the request, runs a few sequential LLM steps, and produces a summary result). It must exercise multi-step progress reporting.
3. Implement `backend/app/orchestration/runner.py`:
   - An `AgentRunner` owning an asyncio task queue: `spawn(spec) -> agent_id` enqueues; a configurable number of workers (default 1) executes agent subgraphs as background tasks.
   - Every lifecycle transition and progress update goes to **both** the `StateStore` agent registry (which publishes `agent_updated` via the existing notify hook) and the audit layer as `AgentEvent`s.
   - Failure isolation: an agent exception marks that agent `failed` (with error summary) and never disturbs the main service. Cancellation support: `cancel(agent_id)`.
   - Started/stopped in the lifespan handler; on shutdown, running agents are cancelled gracefully and audited as such.
4. Implement `backend/app/orchestration/nodes/agent_spawn.py` and wire the conditional edge in `graph.py`: when `llm_review` indicates background work, the node builds an `AgentSpec`, calls `AgentRunner.spawn()`, and records the agent id in the graph state and decision metadata. The main graph then proceeds to `respond` — the user's answer mentions the spawned agent id and does **not** wait for the agent to finish.
5. LLM access discipline: agents share the single global `LlamaRuntime`; its Step 7 serialization means agent generations interleave with foreground ones. Give foreground (main-graph) calls priority if the runtime queue supports it, or document the FIFO behavior.

## Constraints

- Agents live in `orchestration/agents/`, the runner in `orchestration/runner.py`; state mutations only via `StateStore`; audit only via `AuditService`; model calls only via the injected runtime (all per `docs/Architecture.md`).
- The prompt response latency must not regress: spawning is fire-and-forget.
- Every agent lifecycle event is in Postgres — an agent's full history must be reconstructable from `agent_events` alone.

## Verification

- A prompt that warrants background work (per the review node) returns promptly, naming the spawned agent; `GET /api/runs/{id}` decision metadata records the spawn.
- The agent's progress advances in the `StateStore` (visible via Step 13 events) after the response has already returned, and its `last_result` appears on completion.
- `agent_events` contains the full ordered lifecycle for the agent id.
- A deliberately failing agent lands in `failed` with an audited error, while the service and subsequent prompts remain unaffected.
- Shutdown during a running agent cancels it cleanly and audits the cancellation.
