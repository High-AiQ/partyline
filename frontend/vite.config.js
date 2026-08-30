// vitest's `defineConfig` is vite's plus the `test` block, so the two configs
// stay one file rather than drifting apart as two.
import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { basename, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = fileURLToPath(new URL(".", import.meta.url));
const outDir = fileURLToPath(new URL("../partyline/static", import.meta.url));
const buildId = sourceBuildId();

export default defineConfig(({ command }) => ({
  plugins: [buildManifest(), woff2OnlyKatex(), tailwindcss(), svelte()],
  // Component tests run in jsdom but still resolve packages through Vite.
  // Without this condition Svelte's default server export wins, and `mount()`
  // fails before the browser behavior under test can run.
  ...(command === "build" ? {} : { resolve: { conditions: ["browser"] } }),
  define: {
    // The production bundle knows which source snapshot made it. The server
    // reports the same value from build.json on every WebSocket handshake, so
    // a tab holding an old bundle can reload after a deployment. Leave it
    // blank under `npm run dev`: the dev client intentionally runs ahead of
    // the committed backend bundle it proxies to.
    __PARTYLINE_BUILD__: JSON.stringify(command === "build" ? buildId : ""),
  },
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
    include: ["src/**/*.test.{js,ts}"],
  },
}));

/** Keep the lazy KaTeX asset set to the modern WOFF2 fonts we support. */
function woff2OnlyKatex() {
  return {
    name: "partyline-katex-woff2-only",
    enforce: "pre",
    transform(css, id) {
      if (!id.endsWith("/katex/dist/katex.min.css")) return;
      let replacements = 0;
      const transformed = css.replace(
        /src:(url\([^)]*\.woff2\) format\("woff2"\)),url\([^)]*\.woff\) format\("woff"\),url\([^)]*\.ttf\) format\("truetype"\)/g,
        (_declaration, woff2) => {
          replacements += 1;
          return `src:${woff2}`;
        },
      );
      if (replacements !== 20) {
        throw new Error(`expected 20 KaTeX font declarations, transformed ${replacements}`);
      }
      return { code: transformed, map: null };
    },
  };
}

function buildManifest() {
  return {
    name: "partyline-build-manifest",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "build.json",
        source: JSON.stringify({ build: buildId }) + "\n",
      });
    },
  };
}

/** A deterministic identity for the inputs that can change the runtime UI. */
function sourceBuildId() {
  const files = ["index.html", "package.json", "package-lock.json", "vite.config.js"];
  const visit = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (!entry.name.match(/\.test\.[jt]s$/) && !entry.name.endsWith(".d.ts")) files.push(path);
    }
  };
  visit(join(frontendDir, "src"));

  const hash = createHash("sha256");
  for (const path of files
    .map((path) => (path.startsWith(frontendDir) ? path : join(frontendDir, path)))
    .sort()) {
    const name = relative(frontendDir, path).split(sep).join("/") || basename(path);
    hash.update(name).update("\0").update(readFileSync(path)).update("\0");
  }
  return hash.digest("hex").slice(0, 16);
}

function backend() {
  return `http://127.0.0.1:${process.env.PARTYLINE_PORT || 8642}`;
}
