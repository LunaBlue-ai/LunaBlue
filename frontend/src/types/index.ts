/**
 * TypeScript mirrors of the backend Pydantic schemas.
 *
 * `backend/app/api/schemas/` is the single source of truth; every interface
 * here matches those models field-for-field (snake_case included). Datetimes
 * arrive as ISO 8601 strings.
 */

/** Mirrors `PromptRequest` in `api/schemas/prompt.py`. */
export interface PromptRequest {
  text: string;
  /** Existing session to attach to; omit to have the server create one. */
  session_id?: string | null;
  user_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

/** Terminal status of a prompt request. */
export type PromptStatus = "completed" | "failed";

/** Mirrors `PromptResponse` in `api/schemas/prompt.py`. */
export interface PromptResponse {
  request_id: string;
  session_id: string;
  status: PromptStatus;
  response_text: string;
  created_at: string;
}

/**
 * Run phases the backend reports (`api/schemas/state.py`). The wire type is
 * an open string, so unknown values must still render.
 */
export type RunPhase =
  | "received"
  | "governance"
  | "engineering"
  | "reviewing"
  | "spawning"
  | "responding"
  | "completed"
  | "failed"
  | (string & {});

/** Mirrors `PhaseRecord` in `api/schemas/state.py`. */
export interface PhaseRecord {
  phase: RunPhase;
  node: string | null;
  entered_at: string;
  duration_ms: number | null;
}

/** Mirrors `RunStatus` in `api/schemas/state.py`. */
export interface RunStatus {
  request_id: string;
  session_id: string;
  phase: RunPhase;
  current_node: string | null;
  created_at: string;
  updated_at: string;
  result_summary: string | null;
  error: string | null;
  phases: PhaseRecord[];
}

/** Mirrors `SessionStatus` in `api/schemas/state.py`. */
export interface SessionStatus {
  session_id: string;
  user_id: string | null;
  created_at: string;
  last_activity_at: string;
  runs: RunStatus[];
}

/** Mirrors `SessionSummary` in `api/schemas/state.py` (WebSocket payloads). */
export interface SessionSummary {
  session_id: string;
  user_id: string | null;
  created_at: string;
  last_activity_at: string;
  run_ids: string[];
}

/** Mirrors `AgentTaskRecord` in `api/schemas/state.py` (Step 14). */
export interface AgentTaskRecord {
  task_id: string;
  description: string;
  enqueued_at: string;
}

/** Agent lifecycle states (`api/schemas/state.py`); wire type stays open. */
export type AgentState =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | (string & {});

/**
 * Mirrors `AgentSummary` in `api/schemas/agent.py` (Step 15): the field set
 * shared by `GET /api/agents` items and (as a structural subset) the
 * WebSocket `agent_updated` payload, so both feed the same registry.
 */
export interface AgentSummary {
  agent_id: string;
  kind: string;
  session_id: string | null;
  request_id: string | null;
  state: AgentState;
  created_at: string;
  updated_at: string;
  progress_phase: string | null;
  progress_fraction: number | null;
  last_result: string | null;
  error: string | null;
}

/** Mirrors `AgentStatus` in `api/schemas/state.py` (Step 14, WS payloads). */
export interface AgentStatus extends AgentSummary {
  queued_tasks: AgentTaskRecord[];
}

/** Mirrors `AgentEventRecord` in `api/schemas/agent.py` (Step 15). */
export interface AgentEventRecord {
  event_type: string;
  state: string | null;
  timestamp: string;
  payload: Record<string, unknown> | null;
}

/** Mirrors `AgentDetail` in `api/schemas/agent.py` (Step 15). */
export interface AgentDetail extends AgentSummary {
  task: string | null;
  params: Record<string, unknown> | null;
  /** False when the agent was evicted and reconstructed from the audit log. */
  live: boolean;
  events: AgentEventRecord[];
}

/** Shape of `GET /api/health` (`api/routes/health.py`). */
export interface HealthStatus {
  service: string;
  version: string;
  status: "ok" | (string & {});
}

/** One dependency's readiness check (Step 17). */
export interface ReadinessCheck {
  ok: boolean;
  /** Short state name, e.g. "ok", "unreachable", "unhealthy", "overflowing". */
  detail: string;
  [extra: string]: unknown;
}

/**
 * Shape of `GET /api/health/ready` (`api/routes/health.py`). Answered with
 * the same body at 200 (ready) and 503 (a dependency is unavailable).
 * Step 17 added per-dependency `checks`; the top-level `model`/`database`
 * fields remain for older consumers.
 */
export interface ReadinessStatus {
  service: string;
  version: string;
  /** Loaded model id, or the literal "not_loaded". */
  model: string;
  database?: "ok" | "unreachable" | (string & {});
  status: "ok" | "unavailable" | (string & {});
  /** Per-dependency detail: model, database, audit_queue, agent_runner. */
  checks?: Record<string, ReadinessCheck>;
}
