import { isActiveAgent, useAppState } from "../../state/AppState";

const LABELS = {
  unknown: "Checking backend…",
  connected: "Backend connected",
  unreachable: "Backend unreachable",
} as const;

/** Live-updates channel: socket streaming / HTTP polling / no backend. */
const LIVE_LABELS = {
  live: "Live",
  polling: "Polling",
  disconnected: "Disconnected",
} as const;

/** Model readiness, from GET /api/health/ready (Step 15). */
const MODEL_LABELS = {
  unknown: "Model —",
  loaded: "Model ready",
  not_loaded: "Model not loaded",
} as const;

export function StatusBar() {
  const { connectivity, sessionId, wsStatus, agents, modelStatus } =
    useAppState();
  const liveMode =
    wsStatus === "open"
      ? "live"
      : connectivity === "unreachable"
        ? "disconnected"
        : "polling";
  const activeAgents = Object.values(agents).filter(isActiveAgent).length;
  return (
    <footer className={`status-bar status-${connectivity}`}>
      <span className="status-dot" aria-hidden="true" />
      <span>{LABELS[connectivity]}</span>
      <span className={`status-live live-${liveMode}`}>
        {LIVE_LABELS[liveMode]}
      </span>
      <span className={`status-model model-${modelStatus}`}>
        {MODEL_LABELS[modelStatus]}
      </span>
      <span
        className={`status-agents${activeAgents > 0 ? " agents-active" : ""}`}
        title="Background agents currently pending or running"
      >
        Agents {activeAgents}
      </span>
      {sessionId && <span className="status-session">Session {sessionId}</span>}
    </footer>
  );
}
