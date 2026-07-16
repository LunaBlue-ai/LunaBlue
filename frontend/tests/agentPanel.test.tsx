/**
 * AgentPanel (`components/AgentPanel`) driven end-to-end through the real
 * live-updates pipeline: simulated WebSocket frames flow through
 * `openLiveSocket` → `useWebSocket` → the reducer → the rendered panel.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentPanel } from "../src/components/AgentPanel";
import { useWebSocket } from "../src/hooks/useWebSocket";
import type { AgentDetail } from "../src/types";
import {
  FakeWebSocket,
  jsonResponse,
  makeAgent,
  renderWithState,
  stubFetch,
} from "./helpers";

function LivePanel() {
  useWebSocket();
  return <AgentPanel />;
}

/** Wire shape of WS agent payloads: AgentSummary plus queued_tasks. */
function agentPayload(overrides: Parameters<typeof makeAgent>[0] = {}) {
  return { ...makeAgent(overrides), queued_tasks: [] };
}

function snapshotMessage(agents: ReturnType<typeof agentPayload>[]) {
  return {
    type: "snapshot",
    seq: 1,
    ts: "2026-07-15T10:00:00.000Z",
    payload: { sessions: [], runs: [], agents },
  };
}

let seq = 1;
function agentUpdated(agent: ReturnType<typeof agentPayload>) {
  seq += 1;
  return { type: "agent_updated", seq, ts: agent.updated_at, payload: agent };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Render the live panel with a scripted API and an open fake socket. */
function renderLivePanel(
  apiHandler?: (url: string, init?: RequestInit) => Response,
) {
  const fetchMock = stubFetch(
    apiHandler ?? ((url) => (url === "/api/agents" ? jsonResponse([]) : jsonResponse({ detail: "not found" }, 404))),
  );
  const utils = renderWithState(<LivePanel />);
  const socket = FakeWebSocket.last();
  socket.open();
  return { ...utils, fetchMock, socket };
}

describe("AgentPanel", () => {
  it("shows the empty state until an agent exists", () => {
    renderLivePanel();
    expect(screen.getByText(/No background agents yet/)).toBeInTheDocument();
  });

  it("renders agents from the connect snapshot with their state badges", () => {
    const { socket } = renderLivePanel();
    socket.serverSends(
      snapshotMessage([
        agentPayload({ agent_id: "a-run-1234", state: "running", kind: "research" }),
        agentPayload({
          agent_id: "b-done-5678",
          state: "completed",
          created_at: "2026-07-15T09:00:00.000Z",
          last_result: "found 3 sources",
        }),
      ]),
    );

    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("found 3 sources")).toBeInTheDocument();
    // Shortened ids, newest agent first.
    const ids = screen.getAllByTitle(/^(a-run-1234|b-done-5678)$/);
    expect(ids.map((el) => el.textContent)).toEqual(["a-run-12", "b-done-5"]);
  });

  it("updates a row live as agent_updated events stream in", async () => {
    const { socket } = renderLivePanel();
    socket.serverSends(
      snapshotMessage([agentPayload({ agent_id: "a-1", state: "pending" })]),
    );
    expect(screen.getByText("pending")).toBeInTheDocument();

    socket.serverSends(
      agentUpdated(
        agentPayload({
          agent_id: "a-1",
          state: "running",
          updated_at: "2026-07-15T10:01:00.000Z",
          progress_phase: "collecting",
          progress_fraction: 0.5,
        }),
      ),
    );
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("collecting")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");

    socket.serverSends(
      agentUpdated(
        agentPayload({
          agent_id: "a-1",
          state: "completed",
          updated_at: "2026-07-15T10:02:00.000Z",
          progress_fraction: 1,
          last_result: "summary ready",
        }),
      ),
    );
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("summary ready")).toBeInTheDocument();
    // Terminal agents offer no cancel and no progress meter.
    expect(screen.queryByRole("button", { name: /Cancel/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("removes a row when the backend evicts the agent", () => {
    const { socket } = renderLivePanel();
    socket.serverSends(
      snapshotMessage([agentPayload({ agent_id: "a-1", state: "completed" })]),
    );
    expect(screen.queryByText(/No background agents yet/)).not.toBeInTheDocument();

    socket.serverSends({
      type: "agent_evicted",
      seq: 99,
      ts: "2026-07-15T10:05:00.000Z",
      payload: agentPayload({ agent_id: "a-1", state: "completed" }),
    });
    expect(screen.getByText(/No background agents yet/)).toBeInTheDocument();
  });

  it("cancels an active agent via POST /api/agents/{id}/cancel", async () => {
    const { socket, fetchMock } = renderLivePanel((url, init) => {
      if (url === "/api/agents") {
        return jsonResponse([]);
      }
      if (url === "/api/agents/a-1/cancel" && init?.method === "POST") {
        return jsonResponse(makeAgent({ agent_id: "a-1", state: "running" }), 202);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    socket.serverSends(
      snapshotMessage([agentPayload({ agent_id: "a-1", state: "running" })]),
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/agents/a-1/cancel",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("expands a row into the detail view fetched from the agent API", async () => {
    const detail: AgentDetail = {
      ...makeAgent({ agent_id: "a-1", state: "running" }),
      task: "summarize the moons of Jupiter",
      params: { depth: 2 },
      live: true,
      events: [
        {
          event_type: "spawned",
          state: "pending",
          timestamp: "2026-07-15T10:00:00.000Z",
          payload: null,
        },
      ],
    };
    const { socket } = renderLivePanel((url) => {
      if (url === "/api/agents") {
        return jsonResponse([]);
      }
      if (url === "/api/agents/a-1") {
        return jsonResponse(detail);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    socket.serverSends(
      snapshotMessage([agentPayload({ agent_id: "a-1", state: "running" })]),
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { expanded: false }));

    expect(
      await screen.findByText("summarize the moons of Jupiter"),
    ).toBeInTheDocument();
    expect(screen.getByText("spawned")).toBeInTheDocument();
  });
});
