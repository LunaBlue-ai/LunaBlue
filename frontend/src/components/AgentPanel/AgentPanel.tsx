/**
 * Live background-agent panel (Step 15, docs/Components/WEB.md): one row per
 * agent — shortened id (full on hover, copy button), kind, state badge,
 * progress, last result — with an expandable detail view fetched from
 * `GET /api/agents/{id}` (task, parameters, lifecycle events) and a cancel
 * button while the agent is still cancellable. Rows are linked back to the
 * chat message that spawned them via the shared request id.
 *
 * The panel renders registry state only; every fact comes from the store's
 * `agent_updated` events or the agent APIs — nothing is derived locally.
 */

import { useEffect, useState } from "react";
import { ApiError, cancelAgent, getAgent } from "../../api/client";
import {
  isActiveAgent,
  isTerminalAgentState,
  useAppState,
} from "../../state/AppState";
import type { AgentDetail, AgentSummary } from "../../types";

function shortId(agentId: string): string {
  return agentId.slice(0, 8);
}

function formatFraction(fraction: number | null): string | null {
  return fraction === null ? null : `${Math.round(fraction * 100)}%`;
}

function CopyIdButton({ agentId }: { agentId: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      className="agent-copy"
      title={`Copy agent id ${agentId}`}
      onClick={() => {
        void navigator.clipboard?.writeText(agentId).then(() => setCopied(true));
      }}
    >
      {copied ? "✓" : "⧉"}
    </button>
  );
}

function AgentDetailView({ agent }: { agent: AgentSummary }) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refetch whenever the summary advances, so the expanded view tracks the
  // live lifecycle (updated_at changes on every store mutation).
  useEffect(() => {
    let cancelled = false;
    getAgent(agent.agent_id)
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
          setError(null);
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(
            cause instanceof ApiError ? cause.message : "Failed to load detail.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agent.agent_id, agent.updated_at]);

  if (error) {
    return <div className="agent-detail agent-detail-error">{error}</div>;
  }
  if (!detail) {
    return <div className="agent-detail">Loading…</div>;
  }
  const params =
    detail.params && Object.keys(detail.params).length > 0
      ? JSON.stringify(detail.params, null, 1)
      : null;
  return (
    <div className="agent-detail">
      <dl>
        <dt>Agent id</dt>
        <dd className="agent-mono">{detail.agent_id}</dd>
        {detail.task && (
          <>
            <dt>Task</dt>
            <dd>{detail.task}</dd>
          </>
        )}
        {params && (
          <>
            <dt>Parameters</dt>
            <dd>
              <code>{params}</code>
            </dd>
          </>
        )}
        {detail.error && (
          <>
            <dt>Error</dt>
            <dd className="agent-error-text">{detail.error}</dd>
          </>
        )}
      </dl>
      {!detail.live && (
        <p className="agent-detail-note">
          No longer in live state — reconstructed from the audit record.
        </p>
      )}
      {detail.events.length > 0 && (
        <ol className="agent-events">
          {detail.events.map((event, index) => (
            <li key={index}>
              <span className="agent-event-type">{event.event_type}</span>
              <span className="agent-event-time">
                {new Date(event.timestamp).toLocaleTimeString()}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function AgentRow({
  agent,
  spawnedBy,
}: {
  agent: AgentSummary;
  spawnedBy: string | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const [cancelState, setCancelState] = useState<"idle" | "busy" | "failed">(
    "idle",
  );
  const progress = formatFraction(agent.progress_fraction);

  const requestCancel = () => {
    setCancelState("busy");
    cancelAgent(agent.agent_id)
      // The confirming state change arrives via agent_updated/polling; the
      // button just stops offering until it does.
      .then(() => setCancelState("idle"))
      .catch(() => setCancelState("failed"));
  };

  return (
    <li className={`agent-row agent-${agent.state}`}>
      <div className="agent-row-main">
        <button
          type="button"
          className="agent-expand"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? "▾" : "▸"}
        </button>
        <span className="agent-id agent-mono" title={agent.agent_id}>
          {shortId(agent.agent_id)}
        </span>
        <CopyIdButton agentId={agent.agent_id} />
        <span className="agent-kind">{agent.kind}</span>
        <span className={`agent-state-badge agent-state-${agent.state}`}>
          {agent.state}
        </span>
      </div>
      {isActiveAgent(agent) && (agent.progress_phase || progress) && (
        <div className="agent-progress">
          {agent.progress_phase && <span>{agent.progress_phase}</span>}
          {progress && (
            <>
              <span
                className="agent-progress-track"
                role="progressbar"
                aria-valuenow={Math.round((agent.progress_fraction ?? 0) * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span
                  className="agent-progress-fill"
                  style={{ width: progress }}
                />
              </span>
              <span>{progress}</span>
            </>
          )}
        </div>
      )}
      {agent.last_result && (
        <div className="agent-result" title={agent.last_result}>
          {agent.last_result}
        </div>
      )}
      {agent.error && <div className="agent-error-text">{agent.error}</div>}
      {spawnedBy && (
        <div className="agent-spawned-by" title={spawnedBy}>
          ↳ “{spawnedBy}”
        </div>
      )}
      <div className="agent-row-actions">
        {!isTerminalAgentState(agent.state) && (
          <button
            type="button"
            className="agent-cancel"
            disabled={cancelState === "busy"}
            onClick={requestCancel}
          >
            {cancelState === "failed" ? "Cancel failed — retry" : "Cancel"}
          </button>
        )}
      </div>
      {expanded && <AgentDetailView agent={agent} />}
    </li>
  );
}

export function AgentPanel() {
  const { agents, messages } = useAppState();
  const list = Object.values(agents).sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );

  // Link each agent to the chat message that spawned it (same request id).
  const spawnedBy = (agent: AgentSummary): string | undefined => {
    if (agent.request_id === null) {
      return undefined;
    }
    const message = messages.find(
      (m) => m.role === "user" && m.requestId === agent.request_id,
    );
    if (!message) {
      return undefined;
    }
    return message.text.length > 60
      ? `${message.text.slice(0, 60)}…`
      : message.text;
  };

  return (
    <aside className="agent-panel" aria-label="Background agents">
      <h2 className="agent-panel-title">Agents</h2>
      {list.length === 0 ? (
        <p className="agent-panel-empty">
          No background agents yet. Prompts that need side work will spawn
          them here.
        </p>
      ) : (
        <ul className="agent-list">
          {list.map((agent) => (
            <AgentRow
              key={agent.agent_id}
              agent={agent}
              spawnedBy={spawnedBy(agent)}
            />
          ))}
        </ul>
      )}
    </aside>
  );
}
