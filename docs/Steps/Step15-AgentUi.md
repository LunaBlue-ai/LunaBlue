# Step 15 Prompt — Surface Agents in the UI

Use this prompt to execute Step 15 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/WEB.md`). Steps 1–14 delivered background agents: the `AgentRunner` executes agent subgraphs, the `StateStore` agent registry publishes `agent_updated` events over the existing WebSocket, and `agent_events` audits everything. The UI cannot see any of it yet.

## Objective

Give users live visibility into agents: agent status APIs on the backend, and `AgentPanel` and `StatusBar` components on the frontend fed by WebSocket lifecycle updates.

## Tasks

1. Implement `backend/app/api/schemas/agent.py`: `AgentSummary` (id, kind, state, progress, originating request id, created/updated timestamps) and `AgentDetail` (summary plus task description, parameters, `last_result`, error summary, and recent lifecycle events).
2. Implement `backend/app/api/routes/agents.py`:
   - `GET /api/agents` — list agents from the `StateStore` registry, filterable by state and session, newest first.
   - `GET /api/agents/{agent_id}` — full detail; live agents come from the store, and for agents already evicted from live state, reconstruct the detail from `agent_events` audit (or return 404 with a documented choice — prefer reconstruction, it exercises the audit design).
   - Optional but recommended: `POST /api/agents/{agent_id}/cancel` exposing `AgentRunner.cancel()`.
3. Extend `frontend/src/types/` with the agent types, and `src/api/client.ts` with `listAgents()`, `getAgent()`, `cancelAgent()`.
4. Extend the frontend state context to hold the agent registry, updated by `agent_updated` WebSocket events (with polling fallback via `listAgents()` consistent with Step 13's degradation strategy).
5. Implement `src/components/AgentPanel/`: a live list showing each agent's id (shortened, full on hover/copy), kind, state badge, progress, and last result value (per `docs/Components/WEB.md`); expandable detail view; cancel button when cancellation is exposed. Visually associate agents with the chat message that spawned them (matching request id).
6. Implement `src/components/StatusBar/`: backend connectivity (live / polling / disconnected — from Step 13), current session id, model loaded indicator (from health), and active agent count.
7. Compose the layout: chat remains primary; the agent panel sits alongside or collapses on small widths.

## Constraints

- The UI renders state; it never derives it — agent truth comes from store events and the agent APIs (per `docs/Components/WEB.md`).
- All HTTP goes through `client.ts`; all live updates through the existing `useWebSocket` plumbing — no new connection machinery.
- Keep the panel readable at a glance: state and progress are the primary signals, details are progressive disclosure.

## Verification

- Submit a prompt that spawns an agent: it appears in the AgentPanel immediately (`pending`), progresses live through `running` phases, and shows its `last_result` on completion — all without refresh.
- `GET /api/agents?state=running` returns the expected filtered list while an agent runs.
- Cancelling a running agent from the UI moves it to `cancelled` live, with the matching audit trail in `agent_events`.
- The StatusBar accurately reflects disconnect/reconnect and the active agent count.
- With WebSockets disabled, the panel still updates via polling.
