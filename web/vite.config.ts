// From `vitest/config` rather than `vite`: the same function, with the `test` block typed.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * One config for the app and its tests.
 *
 * The build writes into the Python package, because the bundle is what ships in the wheel —
 * `src/chainlens/ui/static/` is inside `packages = ["src/chainlens"]`, so committing the output
 * there is what makes `pip install` work without Node. A CI job rebuilds and fails on a diff, so
 * a stale bundle cannot ship silently.
 */
export default defineConfig({
  plugins: [react()],
  /**
   * Development only: `npm run dev` serves the app from Vite, and this sends its API calls to a
   * separately started `chainlens ui serve`.
   *
   * Two processes rather than one, so the front end hot-reloads while the server holds a walked
   * graph. The server has no CORS header and serves its own bundle from its own origin — adding
   * one would invite exactly the cross-origin use its loopback-only bind exists to prevent — so
   * the traffic has to pass through Vite's origin to reach it, which is what a proxy does.
   *
   * `changeOrigin: false` keeps the Host header as Vite's, because the server compares nothing
   * against it and rewriting it would be pretending otherwise.
   */
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: false },
    },
  },
  build: {
    outDir: "../src/chainlens/ui/static",
    emptyOutDir: true,
    // A single file per asset rather than hash-suffixed: the committed bundle is diffed by CI,
    // and a content hash in every filename would turn a one-line change into a rename.
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    globals: false,
    setupFiles: ["src/test-setup.ts"],
  },
});
