/**
 * Frontend state: React context + reducer (no state library, per
 * docs/Components/WEB.md). Holds the session id, the chat message list,
 * backend connectivity, and (Step 13) live run progress + socket status.
 * Agent state joins in Step 15.
 */

import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import type { SocketStatus } from "../api/ws";
import type { RunPhase, RunStatus } from "../types";

/** Delivery status of one chat message. */
export type MessageStatus = "pending" | "completed" | "failed";

export type ConnectivityStatus = "unknown" | "connected" | "unreachable";

export interface ChatMessage {
  /** Client-generated id, assigned before the backend responds. */
  id: string;
  role: "user" | "assistant";
  text: string;
  status: MessageStatus;
  /** User-facing error for failed prompts, shown inline in the chat. */
  error?: string;
  /** Backend request id, once known. */
  requestId?: string;
  /** Current backend phase while pending (from run_updated events/polls). */
  livePhase?: RunPhase;
}

export interface AppState {
  /**
   * Client-generated session id, sent with every prompt (the backend upserts
   * sessions by id). Generating it up front — rather than waiting for the
   * first response — lets live run events and the polling fallback be
   * correlated to this tab's prompts while `POST /api/prompt` is still in
   * flight and the run's request id is unknown.
   */
  sessionId: string;
  messages: ChatMessage[];
  connectivity: ConnectivityStatus;
  /** Live-socket status; drives the polling fallback and the indicator. */
  wsStatus: SocketStatus;
}

export const initialAppState: AppState = {
  sessionId: crypto.randomUUID(),
  messages: [],
  connectivity: "unknown",
  wsStatus: "closed",
};

const TERMINAL_PHASES: ReadonlySet<string> = new Set(["completed", "failed"]);

export function isTerminalPhase(phase: RunPhase): boolean {
  return TERMINAL_PHASES.has(phase);
}

export type AppAction =
  /** A prompt left the input box: show it immediately as pending. */
  | { type: "prompt_submitted"; messageId: string; text: string }
  /** The backend answered: resolve the prompt and append the reply. */
  | {
      type: "prompt_completed";
      messageId: string;
      requestId: string;
      sessionId: string;
      responseText: string;
      responseStatus: "completed" | "failed";
    }
  /** The request itself failed (network, HTTP, validation). */
  | { type: "prompt_failed"; messageId: string; error: string }
  | { type: "connectivity_changed"; connectivity: ConnectivityStatus }
  /** A run snapshot arrived (WebSocket event, snapshot resync, or poll). */
  | { type: "run_updated"; run: RunStatus }
  | { type: "ws_status_changed"; wsStatus: SocketStatus };

function updateMessage(
  messages: ChatMessage[],
  id: string,
  patch: Partial<ChatMessage>,
): ChatMessage[] {
  return messages.map((message) =>
    message.id === id ? { ...message, ...patch } : message,
  );
}

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "prompt_submitted":
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: action.messageId,
            role: "user",
            text: action.text,
            status: "pending",
          },
        ],
      };
    case "prompt_completed":
      return {
        ...state,
        sessionId: action.sessionId,
        connectivity: "connected",
        messages: [
          ...updateMessage(state.messages, action.messageId, {
            status: "completed",
            requestId: action.requestId,
          }),
          {
            id: `${action.messageId}:reply`,
            role: "assistant",
            text: action.responseText,
            // A pipeline failure still yields a response body; surface it
            // as a failed assistant message rather than dropping it.
            status: action.responseStatus,
            requestId: action.requestId,
          },
        ],
      };
    case "prompt_failed":
      return {
        ...state,
        messages: updateMessage(state.messages, action.messageId, {
          status: "failed",
          error: action.error,
        }),
      };
    case "connectivity_changed":
      if (state.connectivity === action.connectivity) {
        return state;
      }
      return { ...state, connectivity: action.connectivity };
    case "run_updated": {
      const { run } = action;
      // A message already tied to this run: refresh its live phase.
      const matched = state.messages.find(
        (message) => message.requestId === run.request_id,
      );
      if (matched) {
        if (matched.status !== "pending" || matched.livePhase === run.phase) {
          return state;
        }
        return {
          ...state,
          messages: updateMessage(state.messages, matched.id, {
            livePhase: run.phase,
          }),
        };
      }
      // Otherwise this may be the run for a prompt whose POST is still in
      // flight (the request id is unknown until the response arrives): claim
      // it for the oldest unclaimed pending prompt in our session. Terminal
      // runs are never claimed — they could be older, unrelated runs.
      if (run.session_id !== state.sessionId || isTerminalPhase(run.phase)) {
        return state;
      }
      const unclaimed = state.messages.find(
        (message) =>
          message.role === "user" &&
          message.status === "pending" &&
          message.requestId === undefined,
      );
      if (!unclaimed) {
        return state;
      }
      return {
        ...state,
        messages: updateMessage(state.messages, unclaimed.id, {
          requestId: run.request_id,
          livePhase: run.phase,
        }),
      };
    }
    case "ws_status_changed":
      if (state.wsStatus === action.wsStatus) {
        return state;
      }
      return {
        ...state,
        wsStatus: action.wsStatus,
        // An open socket is proof the backend is reachable.
        connectivity:
          action.wsStatus === "open" ? "connected" : state.connectivity,
      };
  }
}

const StateContext = createContext<AppState | undefined>(undefined);
const DispatchContext = createContext<Dispatch<AppAction> | undefined>(
  undefined,
);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialAppState);
  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>
        {children}
      </DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export function useAppState(): AppState {
  const state = useContext(StateContext);
  if (state === undefined) {
    throw new Error("useAppState must be used within AppStateProvider");
  }
  return state;
}

export function useAppDispatch(): Dispatch<AppAction> {
  const dispatch = useContext(DispatchContext);
  if (dispatch === undefined) {
    throw new Error("useAppDispatch must be used within AppStateProvider");
  }
  return dispatch;
}
