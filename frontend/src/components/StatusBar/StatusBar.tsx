import { useAppState } from "../../state/AppState";

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

export function StatusBar() {
  const { connectivity, sessionId, wsStatus } = useAppState();
  const liveMode =
    wsStatus === "open"
      ? "live"
      : connectivity === "unreachable"
        ? "disconnected"
        : "polling";
  return (
    <footer className={`status-bar status-${connectivity}`}>
      <span className="status-dot" aria-hidden="true" />
      <span>{LABELS[connectivity]}</span>
      <span className={`status-live live-${liveMode}`}>
        {LIVE_LABELS[liveMode]}
      </span>
      {sessionId && <span className="status-session">Session {sessionId}</span>}
    </footer>
  );
}
