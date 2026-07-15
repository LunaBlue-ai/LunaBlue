import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev workflow (docs/Architecture.md): the UI runs on the Vite dev server and
// proxies API/WebSocket traffic to the FastAPI backend on :8000. For
// deployment, scripts/build_frontend copies dist/ into backend/app/static.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: (proxy) => {
          // When FastAPI is down, answer with the same shape a real
          // unreachable backend would (503 + JSON detail) instead of
          // http-proxy's opaque 500, so the UI's error handling behaves
          // identically in dev and production.
          proxy.on("error", (_err, _req, res) => {
            if ("writeHead" in res) {
              if (!res.headersSent) {
                res.writeHead(503, { "Content-Type": "application/json" });
              }
              res.end(JSON.stringify({ detail: "Backend unreachable." }));
            } else {
              res.end();
            }
          });
        },
      },
      // WebSocket endpoint arrives in Step 13; the proxy entry is ready now.
      "/ws": {
        target: "http://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
