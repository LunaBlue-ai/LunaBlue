# Step 13 Prompt — Stream Live State over WebSockets

Use this prompt to execute Step 13 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/WEB.md`). Steps 1–12 delivered the single-process app: chat UI served by FastAPI, prompt runs tracked in the `StateStore` (whose mutations already funnel through a no-op notify hook from Step 10), and run status readable via `GET /api/runs/{id}`.

## Objective

Make the UI live: a pub/sub bridge from state mutations to a WebSocket endpoint, and a frontend connection with automatic reconnect and polling fallback. Users watch prompt progress in real time without refreshing.

## Tasks

1. Implement `backend/app/state/events.py`:
   - An async `EventBus` with `publish(event)` and `subscribe() -> async iterator` (per-subscriber bounded queues; slow consumers drop-oldest with a logged warning, never block publishers).
   - Typed event payloads: `run_updated` (run snapshot), `session_updated`, and `agent_updated` (shape defined now, used in Step 14). Each event carries a monotonic sequence number and timestamp.
   - Attach the bus to the Step 10 notify hook: every `StateStore` mutation publishes the corresponding event. The store itself still knows nothing about WebSockets.
2. Implement `backend/app/api/websocket.py`:
   - A `/ws` endpoint: on connect, send a `snapshot` message (current sessions/runs from the store) so clients start consistent, then stream subsequent events.
   - Handle disconnects cleanly (unsubscribe, no leaked tasks); support many concurrent clients; honor `settings.ws_enabled`.
   - Define the wire format explicitly: `{type, seq, ts, payload}` — document it in the module docstring; the frontend mirrors it.
3. Implement `frontend/src/api/ws.ts` and a `useWebSocket` hook:
   - Connect to `/ws` (same origin; the Step 11 dev proxy already forwards it), dispatch events into the frontend state context.
   - Reconnect with capped exponential backoff; on reconnect, rely on the `snapshot` message to resync.
   - **Polling fallback** (per `docs/Components/WEB.md`): if the socket is unavailable, poll `GET /api/runs/{id}` for in-flight prompts at a modest interval, and switch back when the socket recovers.
4. Surface liveness in the UI: the pending chat message now shows the run's current phase (from `run_updated` events), and a connection indicator shows live / polling / disconnected.

## Constraints

- Orchestration and store code never import WebSocket machinery; `state/events.py` is the only bridge to `api/websocket.py` (per `docs/Architecture.md`).
- The UI must remain fully functional with WebSockets disabled — degraded to polling, not broken.
- Events are notifications derived from store snapshots — no business data flows *into* the backend over the socket.

## Verification

- Submit a prompt in the UI: the message's phase updates live (governance → engineering → reviewing → responding → completed) with no refresh and no polling traffic in the network tab.
- Kill and restart the backend: the UI shows disconnected, falls back cleanly, reconnects, and resyncs from the snapshot.
- With `WS_ENABLED=false`, prompt progress still updates via polling.
- Two browser tabs both receive live updates for the same run.
