import { useEffect, useState } from "react";
import { getHealth, getReadiness } from "./api/client";
import type { ReadinessStatus } from "./types";
import { AgentPanel } from "./components/AgentPanel";
import { Chat } from "./components/Chat";
import { StatusBar } from "./components/StatusBar";
import { useWebSocket } from "./hooks/useWebSocket";
import {
  isActiveAgent,
  useAppDispatch,
  useAppState,
  type ModelStatus,
} from "./state/AppState";

/** Readiness can change at runtime (Step 17); refresh it on this cadence. */
const READINESS_POLL_MS = 15_000;

/** Model state from a readiness body, preferring the Step 17 checks. */
function modelStatusOf(readiness: ReadinessStatus): ModelStatus {
  if (readiness.model === "not_loaded") {
    return "not_loaded";
  }
  if (readiness.checks?.model && !readiness.checks.model.ok) {
    return "unhealthy";
  }
  return "loaded";
}

/** Names of the readiness checks currently failing. */
function readinessIssuesOf(readiness: ReadinessStatus): string[] {
  if (!readiness.checks) {
    // Pre-Step-17 body: only the overall verdict is known.
    return readiness.status === "ok" ? [] : ["backend"];
  }
  return Object.entries(readiness.checks)
    .filter(([, check]) => !check.ok)
    .map(([name]) => name);
}

export default function App() {
  const dispatch = useAppDispatch();
  const { connectivity, agents } = useAppState();
  // Chat stays primary; the agent panel sits alongside and can be collapsed
  // (index.css stacks it below the chat on narrow widths).
  const [panelOpen, setPanelOpen] = useState(true);
  const activeAgents = Object.values(agents).filter(isActiveAgent).length;

  // Live updates: /ws socket with reconnect, plus the polling fallback.
  useWebSocket();

  // One health probe on load so the status bar starts truthful; after that,
  // the socket status and each prompt/poll outcome keep it current.
  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then(() => {
        if (!cancelled) {
          dispatch({ type: "connectivity_changed", connectivity: "connected" });
        }
      })
      .catch(() => {
        if (!cancelled) {
          dispatch({
            type: "connectivity_changed",
            connectivity: "unreachable",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  // Readiness detail for the StatusBar: probed when the backend (re)appears
  // and refreshed periodically after that — dependencies can degrade and
  // recover at runtime (database outage, model crash, audit backpressure;
  // Step 17), so a single startup probe would go stale.
  useEffect(() => {
    if (connectivity !== "connected") {
      return undefined;
    }
    let cancelled = false;
    const probe = () => {
      getReadiness()
        .then((readiness) => {
          if (!cancelled) {
            dispatch({
              type: "model_status_changed",
              modelStatus: modelStatusOf(readiness),
              readinessIssues: readinessIssuesOf(readiness),
            });
          }
        })
        .catch(() => {
          if (!cancelled) {
            dispatch({
              type: "model_status_changed",
              modelStatus: "unknown",
              readinessIssues: [],
            });
          }
        });
    };
    probe();
    const timer = window.setInterval(probe, READINESS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [connectivity, dispatch]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>LunaBlue</h1>
        <button
          type="button"
          className="agent-panel-toggle"
          aria-expanded={panelOpen}
          onClick={() => setPanelOpen((open) => !open)}
        >
          Agents{activeAgents > 0 ? ` (${activeAgents})` : ""}
        </button>
      </header>
      <div className="app-body">
        <Chat />
        {panelOpen && <AgentPanel />}
      </div>
      <StatusBar />
    </div>
  );
}
