/**
 * Owns the live-updates channel (Step 13): a `/ws` socket (src/api/ws.ts)
 * dispatching run events into app state, plus the polling fallback from
 * docs/Components/WEB.md — while the socket is down and a prompt is in
 * flight, run status is polled over HTTP instead, and the socket's automatic
 * reconnect switches back to live updates (resyncing from the connect-time
 * `snapshot` message).
 *
 * Polling detail: `POST /api/prompt` is synchronous, so a pending prompt has
 * no request id until it finishes. Until a run event claims one, the poller
 * discovers the in-flight run via `GET /api/sessions/{id}` (the session id
 * is client-generated, so it is known up front); once the message has a
 * request id it polls `GET /api/runs/{id}` directly.
 */

import { useEffect, useRef } from "react";
import { ApiError, getRun, getSession } from "../api/client";
import { openLiveSocket, type ServerMessage } from "../api/ws";
import {
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
  const { wsStatus, sessionId, messages } = useAppState();

  // The socket lives for the app's lifetime; reconnect/backoff is internal.
  useEffect(() => {
    return openLiveSocket({
      onStatus: (status) =>
        dispatch({ type: "ws_status_changed", wsStatus: status }),
      onMessage: (message: ServerMessage) => {
        switch (message.type) {
          case "snapshot":
            // Post-(re)connect resync: replay the live runs as updates.
            for (const run of message.payload.runs) {
              dispatch({ type: "run_updated", run });
            }
            break;
          case "run_updated":
            dispatch({ type: "run_updated", run: message.payload });
            break;
          default:
            // session_updated / agent_updated / run_evicted: nothing in the
            // UI consumes these yet (agents arrive in Step 15).
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
}
