/**
 * Vitest setup for the frontend suite: jest-dom matchers, RTL cleanup, and
 * the browser APIs jsdom does not implement.
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { webcrypto } from "node:crypto";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// jsdom has no scrollIntoView (MessageList auto-scrolls on new messages).
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// AppState generates session ids with crypto.randomUUID.
if (typeof globalThis.crypto?.randomUUID !== "function") {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  });
}
