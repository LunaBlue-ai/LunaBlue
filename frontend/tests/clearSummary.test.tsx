/**
 * Clear-chat-summary button (`components/Chat/ClearSummaryButton`, Step 20):
 * posts to the session's summary reset endpoint and shows a transient
 * confirmation; failures surface as a retryable label.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chat } from "../src/components/Chat";
import { jsonResponse, renderWithState, stubFetch } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("clear chat summary", () => {
  it("posts the reset for the current session and confirms", async () => {
    const fetchMock = stubFetch((url) => {
      if (String(url).endsWith("/summary/reset")) {
        return jsonResponse({ session_id: "s-1", cleared: true });
      }
      throw new Error(`unexpected fetch: ${String(url)}`);
    });
    const user = userEvent.setup();
    const { getState } = renderWithState(<Chat />);

    await user.click(
      screen.getByRole("button", { name: "Clear chat summary" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/sessions/${getState().sessionId}/summary/reset`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(
      await screen.findByRole("button", { name: "Cleared ✓" }),
    ).toBeInTheDocument();
  });

  it("shows a retryable failure label when the reset fails", async () => {
    stubFetch(() => jsonResponse({ detail: "boom" }, 500));
    const user = userEvent.setup();
    renderWithState(<Chat />);

    await user.click(
      screen.getByRole("button", { name: "Clear chat summary" }),
    );

    expect(
      await screen.findByRole("button", { name: "Clear failed — retry" }),
    ).toBeInTheDocument();
  });
});
