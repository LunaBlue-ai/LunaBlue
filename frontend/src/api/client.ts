/**
 * The only module that talks HTTP to the backend. Components never call
 * `fetch` directly (docs/Components/WEB.md); they go through these functions
 * so error handling and the wire contract live in one place.
 *
 * Every failure is normalized to an `ApiError` with a `kind` the UI can
 * branch on: "network" (backend unreachable), "validation" (FastAPI 422
 * with field details), or "http" (any other non-2xx).
 */

import type {
  AgentDetail,
  AgentState,
  AgentSummary,
  HealthStatus,
  Identity,
  PromptRequest,
  PromptResponse,
  ReadinessStatus,
  RunStatus,
  SessionStatus,
  SummaryResetResponse,
} from "../types";

/** Same-origin base path; the Vite dev server proxies it to FastAPI. */
const API_BASE = "/api";

export type ApiErrorKind = "network" | "http" | "validation";

/** One entry of a FastAPI 422 `detail` array. */
export interface ValidationDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status code; undefined for network errors. */
  readonly status?: number;
  /** Field-level details when the backend returned a 422. */
  readonly details?: ValidationDetail[];

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number; details?: ValidationDetail[]; cause?: unknown } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status;
    this.details = options.details;
  }
}

function isValidationDetailArray(value: unknown): value is ValidationDetail[] {
  return (
    Array.isArray(value) &&
    value.every(
      (entry) =>
        typeof entry === "object" &&
        entry !== null &&
        typeof (entry as ValidationDetail).msg === "string",
    )
  );
}

/** Build an ApiError from a non-2xx response, reading its JSON body if any. */
async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    detail = undefined;
  }
  if (response.status === 422 && isValidationDetailArray(detail)) {
    const summary = detail.map((entry) => entry.msg).join("; ");
    return new ApiError("validation", summary || "Invalid request.", {
      status: response.status,
      details: detail,
    });
  }
  const message =
    typeof detail === "string"
      ? detail
      : `Request failed with status ${response.status}.`;
  // Gateway-level failures mean the backend itself is unreachable — the
  // Vite dev proxy and production reverse proxies both answer this way.
  if ([502, 503, 504].includes(response.status)) {
    return new ApiError("network", message, { status: response.status });
  }
  return new ApiError("http", message, { status: response.status });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (cause) {
    throw new ApiError("network", "Cannot reach the LunaBlue backend.", {
      cause,
    });
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  return (await response.json()) as T;
}

/** POST /api/prompt — submit a prompt and wait for the model's answer. */
export function submitPrompt(body: PromptRequest): Promise<PromptResponse> {
  return request<PromptResponse>("/prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** GET /api/runs/{id} — live status of one prompt run. */
export function getRun(requestId: string): Promise<RunStatus> {
  return request<RunStatus>(`/runs/${encodeURIComponent(requestId)}`);
}

/** GET /api/sessions/{id} — session metadata plus recent runs. */
export function getSession(
  sessionId: string,
  limit?: number,
): Promise<SessionStatus> {
  const query = limit !== undefined ? `?limit=${limit}` : "";
  return request<SessionStatus>(
    `/sessions/${encodeURIComponent(sessionId)}${query}`,
  );
}

/** GET /api/health — service liveness. */
export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>("/health");
}

/**
 * GET /api/health/ready — dependency readiness (model loaded, database
 * reachable). A 503 is a valid answer carrying the same body shape, so it is
 * returned as data rather than thrown.
 */
export async function getReadiness(): Promise<ReadinessStatus> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/health/ready`);
  } catch (cause) {
    throw new ApiError("network", "Cannot reach the LunaBlue backend.", {
      cause,
    });
  }
  if (response.ok || response.status === 503) {
    // Clone: a non-JSON 503 (e.g. from the dev proxy with the backend down)
    // must still be readable by errorFromResponse below.
    const body = (await response
      .clone()
      .json()
      .catch(() => undefined)) as ReadinessStatus | undefined;
    if (body && typeof body.status === "string") {
      return body;
    }
  }
  throw await errorFromResponse(response);
}

/** Filters accepted by `GET /api/agents`. */
export interface AgentListFilter {
  state?: AgentState;
  sessionId?: string;
}

/** GET /api/agents — background agents in live state, newest first. */
export function listAgents(filter: AgentListFilter = {}): Promise<AgentSummary[]> {
  const query = new URLSearchParams();
  if (filter.state !== undefined) {
    query.set("state", filter.state);
  }
  if (filter.sessionId !== undefined) {
    query.set("session_id", filter.sessionId);
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return request<AgentSummary[]>(`/agents${suffix}`);
}

/** GET /api/agents/{id} — full detail, reconstructed from audit if evicted. */
export function getAgent(agentId: string): Promise<AgentDetail> {
  return request<AgentDetail>(`/agents/${encodeURIComponent(agentId)}`);
}

/** POST /api/agents/{id}/cancel — request cancellation (asynchronous). */
export function cancelAgent(agentId: string): Promise<AgentSummary> {
  return request<AgentSummary>(
    `/agents/${encodeURIComponent(agentId)}/cancel`,
    { method: "POST" },
  );
}

/**
 * POST /api/sessions/{id}/summary/reset — clear the assistant's internal
 * rolling summary of this conversation (Step 20). Idempotent; identity
 * fields are unaffected.
 */
export function resetChatSummary(
  sessionId: string,
): Promise<SummaryResetResponse> {
  return request<SummaryResetResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/summary/reset`,
    { method: "POST" },
  );
}

/** GET /api/identity — the identity fields pinned into the chat summary. */
export function getIdentity(): Promise<Identity> {
  return request<Identity>("/identity");
}

/** PUT /api/identity — full replace; omitted fields are blanked. */
export function updateIdentity(identity: Identity): Promise<Identity> {
  return request<Identity>("/identity", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(identity),
  });
}
