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
