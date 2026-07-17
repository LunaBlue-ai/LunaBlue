/**
 * Identity panel (`components/IdentityPanel`, Step 20): loads the current
 * fields from GET /api/identity, saves edits via PUT (full replace), and
 * shows a transient confirmation.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IdentityPanel } from "../src/components/IdentityPanel";
import { jsonResponse, renderWithState, stubFetch } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

const IDENTITY = {
  name: "Luna",
  age: "7",
  occupation: "assistant",
  personality: "curious",
  interests: "cats",
};

describe("identity panel", () => {
  it("loads the current identity into the inputs", async () => {
    stubFetch((url, init) => {
      if (String(url) === "/api/identity" && !init?.method) {
        return jsonResponse(IDENTITY);
      }
      throw new Error(`unexpected fetch: ${String(url)}`);
    });
    renderWithState(<IdentityPanel />);

    expect(await screen.findByLabelText("Name")).toHaveValue("Luna");
    expect(screen.getByLabelText("Age")).toHaveValue("7");
    expect(screen.getByLabelText("Occupation")).toHaveValue("assistant");
    expect(screen.getByLabelText("Personality")).toHaveValue("curious");
    expect(screen.getByLabelText("Interests")).toHaveValue("cats");
  });

  it("saves edits with a full-replace PUT and confirms", async () => {
    const fetchMock = stubFetch((url, init) => {
      if (String(url) !== "/api/identity") {
        throw new Error(`unexpected fetch: ${String(url)}`);
      }
      if (init?.method === "PUT") {
        return jsonResponse(JSON.parse(String(init.body)));
      }
      return jsonResponse(IDENTITY);
    });
    const user = userEvent.setup();
    renderWithState(<IdentityPanel />);

    const name = await screen.findByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Zed");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
      expect(put).toBeDefined();
      expect(JSON.parse(String(put![1]?.body))).toEqual({
        ...IDENTITY,
        name: "Zed",
      });
    });
    expect(
      await screen.findByRole("button", { name: "Saved ✓" }),
    ).toBeInTheDocument();
  });

  it("surfaces a load failure without blocking saves", async () => {
    stubFetch((_url, init) => {
      if (init?.method === "PUT") {
        return jsonResponse(JSON.parse(String(init.body)));
      }
      return jsonResponse({ detail: "boom" }, 500);
    });
    renderWithState(<IdentityPanel />);

    expect(
      await screen.findByText(/Could not load the current identity/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });
});
