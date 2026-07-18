/**
 * Reducer logic for chat, run, and agent events (`state/AppState.tsx`).
 * Pure unit tests: every UI fact derives from this reducer, so its claiming,
 * idempotency, and staleness rules are pinned here.
 */

import { describe, expect, it } from "vitest";

import {
  appReducer,
  initialAppState,
  isActiveAgent,
  isTerminalAgentState,
  isTerminalPhase,
  type AppAction,
  type AppState,
} from "../src/state/AppState";
import { makeAgent, makeRun } from "./helpers";

function reduce(state: AppState, ...actions: AppAction[]): AppState {
  return actions.reduce(appReducer, state);
}

function stateWithPendingPrompt(text = "hello") {
  const state = reduce(
    { ...initialAppState, sessionId: "s-1" },
    { type: "prompt_submitted", messageId: "m-1", text },
  );
  return state;
}

describe("prompt lifecycle", () => {
  it("prompt_submitted appends a pending user message", () => {
    const state = stateWithPendingPrompt("hi there");
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({
      id: "m-1",
      role: "user",
      text: "hi there",
      status: "pending",
    });
  });

  it("prompt_completed resolves the prompt and appends the reply", () => {
    const state = reduce(stateWithPendingPrompt(), {
      type: "prompt_completed",
      messageId: "m-1",
      requestId: "r-1",
      sessionId: "s-server",
      responseText: "echo: hello",
      responseStatus: "completed",
    });
    expect(state.sessionId).toBe("s-server");
    expect(state.connectivity).toBe("connected");
    const [user, reply] = state.messages;
    expect(user).toMatchObject({ status: "completed", requestId: "r-1" });
    expect(reply).toMatchObject({
      role: "assistant",
      text: "echo: hello",
      status: "completed",
      requestId: "r-1",
    });
  });

  it("a failed pipeline response surfaces as a failed assistant message", () => {
    const state = reduce(stateWithPendingPrompt(), {
      type: "prompt_completed",
      messageId: "m-1",
      requestId: "r-1",
      sessionId: "s-1",
      responseText: "Something went wrong generating a response.",
      responseStatus: "failed",
    });
    expect(state.messages[1].status).toBe("failed");
  });

  it("prompt_failed marks the message failed with the error inline", () => {
    const state = reduce(stateWithPendingPrompt(), {
      type: "prompt_failed",
      messageId: "m-1",
      error: "Cannot reach the LunaBlue backend.",
    });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({
      status: "failed",
      error: "Cannot reach the LunaBlue backend.",
    });
  });
});

describe("run events", () => {
  it("claims an unclaimed pending prompt for a live run in this session", () => {
    const run = makeRun({ request_id: "r-9", session_id: "s-1", phase: "governance" });
    const state = reduce(stateWithPendingPrompt(), { type: "run_updated", run });
    expect(state.messages[0]).toMatchObject({
      requestId: "r-9",
      livePhase: "governance",
    });
  });

  it("never claims runs from another session or terminal runs", () => {
    const otherSession = makeRun({ session_id: "s-other", phase: "governance" });
    const terminal = makeRun({ session_id: "s-1", phase: "completed" });
    let state = stateWithPendingPrompt();
    state = reduce(
      state,
      { type: "run_updated", run: otherSession },
      { type: "run_updated", run: terminal },
    );
    expect(state.messages[0].requestId).toBeUndefined();
  });

  it("updates the live phase of an already-claimed pending prompt", () => {
    let state = stateWithPendingPrompt();
    state = reduce(
      state,
      { type: "run_updated", run: makeRun({ request_id: "r-9", session_id: "s-1", phase: "engineering" }) },
      { type: "run_updated", run: makeRun({ request_id: "r-9", session_id: "s-1", phase: "responding" }) },
    );
    expect(state.messages[0].livePhase).toBe("responding");
  });

  it("ignores run updates for settled messages (idempotent no-op)", () => {
    let state = reduce(stateWithPendingPrompt(), {
      type: "prompt_completed",
      messageId: "m-1",
      requestId: "r-1",
      sessionId: "s-1",
      responseText: "done",
      responseStatus: "completed",
    });
    const next = reduce(state, {
      type: "run_updated",
      run: makeRun({ request_id: "r-1", session_id: "s-1", phase: "completed" }),
    });
    expect(next).toBe(state);
  });
});

describe("agent events", () => {
  it("agent_updated upserts into the registry", () => {
    const agent = makeAgent({ agent_id: "a-1", state: "running" });
    const state = reduce(initialAppState, { type: "agent_updated", agent });
    expect(state.agents["a-1"].state).toBe("running");
  });

  it("drops stale agent snapshots (older updated_at never rolls back)", () => {
    const newer = makeAgent({
      agent_id: "a-1",
      state: "completed",
      updated_at: "2026-07-15T10:05:00.000Z",
    });
    const stale = makeAgent({
      agent_id: "a-1",
      state: "running",
      updated_at: "2026-07-15T10:01:00.000Z",
    });
    const state = reduce(
      initialAppState,
      { type: "agent_updated", agent: newer },
      { type: "agent_updated", agent: stale },
    );
    expect(state.agents["a-1"].state).toBe("completed");
  });

  it("applies same-timestamp snapshots (rapid transitions share a clock tick)", () => {
    const running = makeAgent({ agent_id: "a-1", state: "running" });
    const completed = makeAgent({ agent_id: "a-1", state: "completed" });
    const state = reduce(
      initialAppState,
      { type: "agent_updated", agent: running },
      { type: "agent_updated", agent: completed },
    );
    expect(state.agents["a-1"].state).toBe("completed");
  });

  it("agent_evicted removes the agent; unknown ids are a no-op", () => {
    const withAgent = reduce(initialAppState, {
      type: "agent_updated",
      agent: makeAgent({ agent_id: "a-1" }),
    });
    const evicted = reduce(withAgent, { type: "agent_evicted", agentId: "a-1" });
    expect(evicted.agents).toEqual({});
    expect(reduce(evicted, { type: "agent_evicted", agentId: "a-1" })).toBe(
      evicted,
    );
  });

  it("agents_synced replaces the registry wholesale", () => {
    const before = reduce(initialAppState, {
      type: "agent_updated",
      agent: makeAgent({ agent_id: "a-old" }),
    });
    const state = reduce(before, {
      type: "agents_synced",
      agents: [makeAgent({ agent_id: "a-new" })],
    });
    expect(Object.keys(state.agents)).toEqual(["a-new"]);
  });
});

describe("connectivity and socket status", () => {
  it("an open socket proves the backend is reachable", () => {
    const state = reduce(initialAppState, {
      type: "ws_status_changed",
      wsStatus: "open",
    });
    expect(state.wsStatus).toBe("open");
    expect(state.connectivity).toBe("connected");
  });

  it("a closing socket keeps the last known connectivity", () => {
    const state = reduce(
      initialAppState,
      { type: "ws_status_changed", wsStatus: "open" },
      { type: "ws_status_changed", wsStatus: "closed" },
    );
    expect(state.connectivity).toBe("connected");
  });
});

describe("phase/state helpers", () => {
  it("classifies terminal run phases and agent states", () => {
    expect(isTerminalPhase("completed")).toBe(true);
    expect(isTerminalPhase("responding")).toBe(false);
    expect(isTerminalAgentState("cancelled")).toBe(true);
    expect(isActiveAgent(makeAgent({ state: "running" }))).toBe(true);
    expect(isActiveAgent(makeAgent({ state: "failed" }))).toBe(false);
  });
});
