/**
 * Owns the live-updates channel (Step 13): a `/ws` socket (src/api/ws.ts)
 * dispatching run and agent events into app state, plus the polling fallback
 * from docs/Components/WEB.md — while the socket is down, run status is
 * polled over HTTP for in-flight prompts and `GET /api/agents` for the agent
 * registry (Step 15), and the socket's automatic reconnect switches back to
 * live updates (resyncing from the connect-time `snapshot` message).
 *
 * Polling detail: `POST /api/prompt` is synchronous, so a pending prompt has
 * no request id until it finishes. Until a run event claims one, the poller
 * discovers the in-flight run via `GET /api/sessions/{id}` (the session id
 * is client-generated, so it is known up front); once the message has a
 * request id it polls `GET /api/runs/{id}` directly.
 */

import { useEffect, useRef } from "react";
import { ApiError, getRun, getSession, listAgents } from "../api/client";
import { openLiveSocket, type ServerMessage } from "../api/ws";
import {
  isActiveAgent,
  isTerminalPhase,
  useAppDispatch,
  useAppState,
  type AppAction,
  type ChatMessage,
} from "../state/AppState";

const POLL_INTERVAL_MS = 2000;

function isPendingPrompt(message: ChatMessage): boolean {
  return message.role === "user" && message.status === "pending";
}

export function useWebSocket(): void {
  const dispatch = useAppDispatch();
  const { wsStatus, sessionId, messages, agents } = useAppState();

  // The socket lives for the app's lifetime; reconnect/backoff is internal.
  useEffect(() => {
    return openLiveSocket({
      onStatus: (status) =>
        dispatch({ type: "ws_status_changed", wsStatus: status }),
      onMessage: (message: ServerMessage) => {
        switch (message.type) {
          case "snapshot":
            // Post-(re)connect resync: replay the live runs as updates and
            // replace the agent registry with the server's full list.
            for (const run of message.payload.runs) {
              dispatch({ type: "run_updated", run });
            }
            dispatch({ type: "agents_synced", agents: message.payload.agents });
            break;
          case "run_updated":
            dispatch({ type: "run_updated", run: message.payload });
            break;
          case "agent_updated":
            dispatch({ type: "agent_updated", agent: message.payload });
            break;
          case "agent_evicted":
            dispatch({ type: "agent_evicted", agentId: message.payload.agent_id });
            break;
          default:
            // session_updated / run_evicted: nothing in the UI consumes these.
            break;
        }
      },
    });
  }, [dispatch]);

  // Polling fallback. Reading messages through a ref keeps the interval
  // stable across message updates; the effect only restarts when polling
  // should start or stop.
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const live = wsStatus === "open";
  const hasPendingPrompt = messages.some(isPendingPrompt);

  useEffect(() => {
    if (live || !hasPendingPrompt) {
      return undefined;
    }
    let cancelled = false;
    let inFlight = false;

    const dispatchSafe = (action: AppAction) => {
      if (!cancelled) {
        dispatch(action);
      }
    };

    const poll = async () => {
      if (inFlight || cancelled) {
        return;
      }
      inFlight = true;
      try {
        const pending = messagesRef.current.filter(isPendingPrompt);
        const claimed = pending.filter((m) => m.requestId !== undefined);
        if (claimed.length > 0) {
          for (const message of claimed) {
            const run = await getRun(message.requestId!);
            dispatchSafe({ type: "run_updated", run });
          }
        } else if (pending.length > 0) {
          // No request id yet: discover the in-flight run via the session.
          const session = await getSession(sessionId);
          for (const run of session.runs) {
            if (!isTerminalPhase(run.phase)) {
              dispatchSafe({ type: "run_updated", run });
            }
          }
        }
        dispatchSafe({ type: "connectivity_changed", connectivity: "connected" });
      } catch (error) {
        if (error instanceof ApiError && error.kind === "network") {
          dispatchSafe({
            type: "connectivity_changed",
            connectivity: "unreachable",
          });
        }
        // Other failures (e.g. 404 before the run/session exists, or after
        // eviction) are expected while polling; try again next tick.
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [live, hasPendingPrompt, sessionId, dispatch]);

  // One-shot registry sync on mount (Step 15): with WS disabled there is no
  // connect snapshot, so a freshly loaded page would otherwise show an empty
  // panel until the next prompt spawns an agent. Skipped when the socket
  // opened first — its snapshot is newer.
  const liveRef = useRef(live);
  liveRef.current = live;
  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((agentList) => {
        if (!cancelled && !liveRef.current) {
          dispatch({ type: "agents_synced", agents: agentList });
        }
      })
      .catch(() => {
        // The health probe and pollers own connectivity signaling.
      });
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  // Agent polling fallback (Step 15), same degradation strategy: while the
  // socket is down, resync the registry whenever agents could be changing —
  // a prompt in flight may spawn one (agents register mid-run, before the
  // synchronous POST returns), and known active agents keep progressing
  // after the prompt completes. Each poll replaces the registry, so the
  // final tick after the last agent settles also stops the loop.
  const hasActiveAgents = Object.values(agents).some(isActiveAgent);

  useEffect(() => {
    if (live || (!hasPendingPrompt && !hasActiveAgents)) {
      return undefined;
    }
    let cancelled = false;
    let inFlight = false;

    const poll = async () => {
      if (inFlight || cancelled) {
        return;
      }
      inFlight = true;
      try {
        const agentList = await listAgents();
        if (!cancelled) {
          dispatch({ type: "agents_synced", agents: agentList });
        }
      } catch {
        // Connectivity signaling is the run poller's job; just retry.
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [live, hasPendingPrompt, hasActiveAgents, dispatch]);
}
