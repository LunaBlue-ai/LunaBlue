/**
 * Shared helpers for the frontend suite: rendering inside the real
 * `AppStateProvider` with a captured dispatch/state, wire-shaped test data,
 * and a scriptable `fetch` stub matching the backend's response shapes.
 */

import { act, render } from "@testing-library/react";
import type { Dispatch, ReactNode } from "react";
import { vi } from "vitest";

import {
  AppStateProvider,
  useAppDispatch,
  useAppState,
  type AppAction,
  type AppState,
} from "../src/state/AppState";
import type { AgentSummary, RunStatus } from "../src/types";

/** Render `ui` inside the provider; returns a dispatcher (wrapped in `act`)
 * and a live view of the current state alongside the RTL queries. */
export function renderWithState(ui: ReactNode) {
  const dispatchRef: { current: Dispatch<AppAction> | null } = { current: null };
  const stateRef: { current: AppState | null } = { current: null };

  function Capture() {
    dispatchRef.current = useAppDispatch();
    stateRef.current = useAppState();
    return null;
  }

  const utils = render(
    <AppStateProvider>
      <Capture />
      {ui}
    </AppStateProvider>,
  );
  return {
    ...utils,
    dispatch: (action: AppAction) => {
      act(() => dispatchRef.current!(action));
    },
    getState: () => stateRef.current!,
  };
}

export function makeAgent(overrides: Partial<AgentSummary> = {}): AgentSummary {
  return {
    agent_id: "agent-0001-abcd",
    kind: "research",
    session_id: "s-1",
    request_id: null,
    state: "pending",
    created_at: "2026-07-15T10:00:00.000Z",
    updated_at: "2026-07-15T10:00:00.000Z",
    progress_phase: null,
    progress_fraction: null,
    last_result: null,
    error: null,
    ...overrides,
  };
}

export function makeRun(overrides: Partial<RunStatus> = {}): RunStatus {
  return {
    request_id: "r-1",
    session_id: "s-1",
    phase: "received",
    current_node: null,
    created_at: "2026-07-15T10:00:00.000Z",
    updated_at: "2026-07-15T10:00:00.000Z",
    result_summary: null,
    error: null,
    phases: [],
    ...overrides,
  };
}

/** A `fetch` mock answering with `status` and a JSON `body`. */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Install a scripted global fetch; returns the mock for assertions. */
export function stubFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  const mock = vi.fn(
    (input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
      Promise.resolve(handler(String(input), init)),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

/**
 * Minimal scriptable stand-in for the browser `WebSocket`, letting tests
 * drive the real `openLiveSocket` → `useWebSocket` → reducer pipeline with
 * simulated server frames.
 */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static last(): FakeWebSocket {
    const instance = FakeWebSocket.instances.at(-1);
    if (!instance) {
      throw new Error("no FakeWebSocket was opened");
    }
    return instance;
  }

  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  /** Simulate the server accepting the handshake. */
  open(): void {
    act(() => this.onopen?.());
  }

  /** Simulate one server → client wire message. */
  serverSends(message: unknown): void {
    act(() => this.onmessage?.({ data: JSON.stringify(message) }));
  }
}
