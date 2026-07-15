/**
 * The WebSocket connection to `/ws` — the frontend mirror of
 * `backend/app/api/websocket.py` (its module docstring defines the wire
 * format; keep the two in sync).
 *
 * Every server → client message is `{type, seq, ts, payload}`. The first
 * message after every (re)connect is a `snapshot` carrying the full live
 * state, so reconnecting needs no client-side replay: dispatch the snapshot
 * and every later event as idempotent upserts. The socket is receive-only —
 * nothing is ever sent to the backend over it.
 *
 * `openLiveSocket` keeps the connection alive with capped exponential
 * backoff. It reports status transitions so the caller can run the polling
 * fallback (docs/Components/WEB.md) while the socket is down — including
 * when the backend refuses the handshake because `WS_ENABLED=false`.
 */

import type { AgentStatus, RunStatus, SessionSummary } from "../types";

/** Payload of the connect-time `snapshot` message. */
export interface SnapshotPayload {
  sessions: SessionSummary[];
  runs: RunStatus[];
  agents: AgentStatus[];
}

/** One `{type, seq, ts, payload}` wire message, discriminated on `type`. */
export type ServerMessage =
  | { type: "snapshot"; seq: number; ts: string; payload: SnapshotPayload }
  | { type: "run_updated" | "run_evicted"; seq: number; ts: string; payload: RunStatus }
  | { type: "session_updated"; seq: number; ts: string; payload: SessionSummary }
  | { type: "agent_updated"; seq: number; ts: string; payload: AgentStatus };

export type SocketStatus = "connecting" | "open" | "closed";

export interface LiveSocketHandlers {
  onMessage: (message: ServerMessage) => void;
  onStatus: (status: SocketStatus) => void;
}

const INITIAL_RETRY_MS = 500;
const MAX_RETRY_MS = 10_000;

/** Same-origin endpoint; the Vite dev proxy forwards it to FastAPI. */
function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}

/**
 * Open (and keep reopening) the live socket. Returns a dispose function that
 * stops reconnecting and closes the current connection.
 */
export function openLiveSocket(handlers: LiveSocketHandlers): () => void {
  let socket: WebSocket | null = null;
  let retryMs = INITIAL_RETRY_MS;
  let retryTimer: number | undefined;
  let disposed = false;

  const connect = () => {
    if (disposed) {
      return;
    }
    handlers.onStatus("connecting");
    socket = new WebSocket(socketUrl());

    socket.onopen = () => {
      retryMs = INITIAL_RETRY_MS;
      handlers.onStatus("open");
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        console.warn("Ignoring malformed /ws message");
        return;
      }
      if (typeof message?.type !== "string") {
        return;
      }
      handlers.onMessage(message);
    };

    // A failed handshake also fires onclose, so this single path covers
    // drops, refusals (WS_ENABLED=false), and an unreachable backend.
    socket.onclose = () => {
      socket = null;
      if (disposed) {
        return;
      }
      handlers.onStatus("closed");
      retryTimer = window.setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
    };
  };

  connect();

  return () => {
    disposed = true;
    window.clearTimeout(retryTimer);
    socket?.close();
  };
}
