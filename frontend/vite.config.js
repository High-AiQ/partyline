// vitest's `defineConfig` is vite's plus the `test` block, so the two configs
// stay one file rather than drifting apart as two.
import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const outDir = fileURLToPath(new URL("../partyline/static", import.meta.url));

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  build: {
    outDir,
    // The server serves this directory; anything stale in it is a bug waiting
    // to be served, so the build owns the directory outright.
    emptyOutDir: true,
    // The build output is committed, and a ~900kB source map that changes on
    // every build makes every frontend commit a binary-sized diff. Debugging
    // happens in `npm run dev`, which has maps by default.
    sourcemap: false,
  },
  server: {
    // `npm run dev` proxies to a partyline started on PARTYLINE_PORT, so the
    // frontend can hot-reload against a real server with real processes on it.
    proxy: {
      "/api": { target: backend(), changeOrigin: true },
      "/ws": { target: backend(), ws: true },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.js"],
  },
});

function backend() {
  return `http://127.0.0.1:${process.env.PARTYLINE_PORT || 8642}`;
}
