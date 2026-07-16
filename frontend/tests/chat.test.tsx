/**
 * Chat behavior (`components/Chat`): submit → pending indicator → assistant
 * reply, inline errors on failure, and the live-phase label from run events.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chat } from "../src/components/Chat";
import { jsonResponse, makeRun, renderWithState, stubFetch } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

function promptResponse(text: string, status: "completed" | "failed" = "completed") {
  return {
    request_id: "r-1",
    session_id: "s-1",
    status,
    response_text: text,
    created_at: "2026-07-15T10:00:00.000Z",
  };
}

describe("prompt submission", () => {
  it("shows the pending prompt immediately, then the assistant reply", async () => {
    let resolveFetch: (response: Response) => void;
    stubFetch(() => new Promise<Response>((resolve) => (resolveFetch = resolve)));
    const user = userEvent.setup();
    renderWithState(<Chat />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // Pending: the user message renders at once, the indicator thinks, and
    // the submit button locks until the backend answers.
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText(/Thinking/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Waiting…" })).toBeDisabled();

    resolveFetch!(jsonResponse(promptResponse("echo: hello")));

    expect(await screen.findByText("echo: hello")).toBeInTheDocument();
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("submits with Enter and posts the trimmed prompt to /api/prompt", async () => {
    const fetchMock = stubFetch(() => jsonResponse(promptResponse("ok")));
    const user = userEvent.setup();
    renderWithState(<Chat />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "  hi  {Enter}");

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/prompt");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body)).text).toBe("hi");
  });

  it("renders an HTTP rejection as an inline error on the prompt", async () => {
    stubFetch(() => jsonResponse({ detail: "Prompt rejected by governance." }, 400));
    const user = userEvent.setup();
    renderWithState(<Chat />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "nope{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Prompt rejected by governance.");
    // No assistant reply was fabricated; the failed user message remains.
    expect(screen.getByText("nope")).toBeInTheDocument();
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
  });

  it("marks the backend unreachable on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("fetch failed"))),
    );
    const user = userEvent.setup();
    const { getState } = renderWithState(<Chat />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "hi{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the LunaBlue backend.");
    expect(getState().connectivity).toBe("unreachable");
  });

  it("tracks live run phases in the pending indicator", async () => {
    stubFetch(() => new Promise<Response>(() => {}));
    const user = userEvent.setup();
    const { dispatch, getState } = renderWithState(<Chat />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "hi{Enter}");
    expect(screen.getByText(/Thinking/)).toBeInTheDocument();

    // A run_updated event for this session (WS or poll) claims the prompt.
    dispatch({
      type: "run_updated",
      run: makeRun({
        request_id: "r-live",
        session_id: getState().sessionId,
        phase: "reviewing",
      }),
    });

    expect(screen.getByText(/Reviewing the draft/)).toBeInTheDocument();
  });
});
