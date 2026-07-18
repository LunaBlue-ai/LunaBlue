import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The frontend suite (Step 16) lives in tests/ inside this package — inside
// so every bare import resolves against this package's node_modules; the
// backend's consolidated suite is at the repo root (tests/backend).
// Run with `npm test` here (or see the repo-root README).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    dir: "tests",
    setupFiles: ["tests/setup.ts"],
  },
});
