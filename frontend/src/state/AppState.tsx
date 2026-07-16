/**
 * Frontend state: React context + reducer (no state library, per
 * docs/Components/WEB.md). Holds the session id, the chat message list,
 * backend connectivity, (Step 13) live run progress + socket status, and
 * (Step 15) the agent registry mirrored from the backend store. The UI only
 * renders this state — every agent fact originates in an `agent_updated`
 * event, a snapshot, or an `/api/agents` poll; nothing is derived locally.
 */

import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import type { SocketStatus } from "../api/ws";
import type { AgentState, AgentSummary, RunPhase, RunStatus } from "../types";

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

/** Model state, from `GET /api/health/ready`. `unhealthy` means loaded but
 * the last generation crashed (Step 17); the runtime self-heals on the next
 * successful generation. */
export type ModelStatus = "unknown" | "loaded" | "not_loaded" | "unhealthy";

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
  /** Agent registry mirrored from the backend store, keyed by agent id. */
  agents: Record<string, AgentSummary>;
  modelStatus: ModelStatus;
  /**
   * Names of readiness checks currently failing (Step 17): e.g. "database",
   * "audit_queue". Empty while everything is ready (or unknown).
   */
  readinessIssues: string[];
  /** Backend version from GET /api/health (Step 18); null until known. */
  backendVersion: string | null;
}

export const initialAppState: AppState = {
  sessionId: crypto.randomUUID(),
  messages: [],
  connectivity: "unknown",
  wsStatus: "closed",
  agents: {},
  modelStatus: "unknown",
  readinessIssues: [],
  backendVersion: null,
};

const TERMINAL_PHASES: ReadonlySet<string> = new Set(["completed", "failed"]);

export function isTerminalPhase(phase: RunPhase): boolean {
  return TERMINAL_PHASES.has(phase);
}

const TERMINAL_AGENT_STATES: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export function isTerminalAgentState(state: AgentState): boolean {
  return TERMINAL_AGENT_STATES.has(state);
}

/** Agents still doing (or waiting to do) work — the StatusBar count. */
export function isActiveAgent(agent: AgentSummary): boolean {
  return !isTerminalAgentState(agent.state);
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
  | {
      type: "connectivity_changed";
      connectivity: ConnectivityStatus;
      /** Backend version, when the probe that proved connectivity knows it. */
      backendVersion?: string;
    }
  /** A run snapshot arrived (WebSocket event, snapshot resync, or poll). */
  | { type: "run_updated"; run: RunStatus }
  | { type: "ws_status_changed"; wsStatus: SocketStatus }
  /** One agent snapshot arrived (WebSocket `agent_updated`). */
  | { type: "agent_updated"; agent: AgentSummary }
  /** A settled agent left the backend's live-state retention window. */
  | { type: "agent_evicted"; agentId: string }
  /** Authoritative full agent list (connect snapshot or `/api/agents` poll). */
  | { type: "agents_synced"; agents: AgentSummary[] }
  | {
      type: "model_status_changed";
      modelStatus: ModelStatus;
      /** Failing readiness check names; omitted means "unchanged". */
      readinessIssues?: string[];
    };

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
    case "connectivity_changed": {
      const backendVersion = action.backendVersion ?? state.backendVersion;
      if (
        state.connectivity === action.connectivity &&
        state.backendVersion === backendVersion
      ) {
        return state;
      }
      return { ...state, connectivity: action.connectivity, backendVersion };
    }
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
    case "agent_updated": {
      const { agent } = action;
      const existing = state.agents[agent.agent_id];
      // Upserts are idempotent; a poll result racing a socket event must not
      // roll an agent backwards, so older snapshots are dropped.
      if (existing && existing.updated_at > agent.updated_at) {
        return state;
      }
      return {
        ...state,
        agents: { ...state.agents, [agent.agent_id]: agent },
      };
    }
    case "agent_evicted": {
      if (!(action.agentId in state.agents)) {
        return state;
      }
      const agents = { ...state.agents };
      delete agents[action.agentId];
      return { ...state, agents };
    }
    case "agents_synced": {
      // Server truth replaces the registry wholesale: it also drops agents
      // evicted while the socket was down.
      const agents: Record<string, AgentSummary> = {};
      for (const agent of action.agents) {
        agents[agent.agent_id] = agent;
      }
      return { ...state, agents };
    }
    case "model_status_changed": {
      const readinessIssues = action.readinessIssues ?? state.readinessIssues;
      if (
        state.modelStatus === action.modelStatus &&
        readinessIssues.length === state.readinessIssues.length &&
        readinessIssues.every((issue, i) => issue === state.readinessIssues[i])
      ) {
        return state;
      }
      return { ...state, modelStatus: action.modelStatus, readinessIssues };
    }
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
