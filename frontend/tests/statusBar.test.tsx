/**
 * StatusBar connectivity states (`components/StatusBar`): backend
 * reachability, live/polling/disconnected channel, model readiness, and the
 * active-agent count.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBar } from "../src/components/StatusBar";
import { makeAgent, renderWithState } from "./helpers";

describe("StatusBar", () => {
  it("starts checking the backend, on the polling channel, model unknown", () => {
    renderWithState(<StatusBar />);
    expect(screen.getByText("Checking backend…")).toBeInTheDocument();
    expect(screen.getByText("Polling")).toBeInTheDocument();
    expect(screen.getByText("Model —")).toBeInTheDocument();
    expect(screen.getByText("Agents 0")).toBeInTheDocument();
  });

  it("an open socket shows connected + live", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    dispatch({ type: "ws_status_changed", wsStatus: "open" });
    expect(screen.getByText("Backend connected")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("a closed socket with a reachable backend degrades to polling", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    dispatch({ type: "ws_status_changed", wsStatus: "open" });
    dispatch({ type: "ws_status_changed", wsStatus: "closed" });
    expect(screen.getByText("Backend connected")).toBeInTheDocument();
    expect(screen.getByText("Polling")).toBeInTheDocument();
  });

  it("an unreachable backend shows disconnected", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    dispatch({ type: "connectivity_changed", connectivity: "unreachable" });
    expect(screen.getByText("Backend unreachable")).toBeInTheDocument();
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });

  it("reflects model readiness from the readiness probe", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    dispatch({ type: "model_status_changed", modelStatus: "loaded" });
    expect(screen.getByText("Model ready")).toBeInTheDocument();
    dispatch({ type: "model_status_changed", modelStatus: "not_loaded" });
    expect(screen.getByText("Model not loaded")).toBeInTheDocument();
  });

  it("counts only agents still pending or running", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    dispatch({
      type: "agents_synced",
      agents: [
        makeAgent({ agent_id: "a-1", state: "running" }),
        makeAgent({ agent_id: "a-2", state: "pending" }),
        makeAgent({ agent_id: "a-3", state: "completed" }),
        makeAgent({ agent_id: "a-4", state: "cancelled" }),
      ],
    });
    expect(screen.getByText("Agents 2")).toBeInTheDocument();
  });

  it("shows the session id", () => {
    const { getState } = renderWithState(<StatusBar />);
    expect(
      screen.getByText(`Session ${getState().sessionId}`),
    ).toBeInTheDocument();
  });

  // Step 17: readiness detail.

  it("shows an unhealthy model distinctly from a missing one", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    dispatch({
      type: "model_status_changed",
      modelStatus: "unhealthy",
      readinessIssues: ["model"],
    });
    expect(screen.getByText("Model unhealthy")).toBeInTheDocument();
  });

  it("surfaces failing readiness checks and clears them on recovery", () => {
    const { dispatch } = renderWithState(<StatusBar />);
    expect(screen.queryByText(/^Degraded:/)).not.toBeInTheDocument();

    dispatch({
      type: "model_status_changed",
      modelStatus: "loaded",
      readinessIssues: ["database", "audit_queue"],
    });
    expect(
      screen.getByText("Degraded: database, audit_queue"),
    ).toBeInTheDocument();

    dispatch({
      type: "model_status_changed",
      modelStatus: "loaded",
      readinessIssues: [],
    });
    expect(screen.queryByText(/^Degraded:/)).not.toBeInTheDocument();
  });
});
