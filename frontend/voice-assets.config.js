/** Local, pinned VAD assets. No CDN request is needed to listen. */
import { readFileSync } from "node:fs";
const files = {
  "vad.worklet.bundle.min.js": "@ricky0123/vad-web/dist/vad.worklet.bundle.min.js",
  "silero_vad_v5.onnx": "@ricky0123/vad-web/dist/silero_vad_v5.onnx",
  "ort-wasm-simd-threaded.mjs": "onnxruntime-web/dist/ort-wasm-simd-threaded.mjs",
  "ort-wasm-simd-threaded.wasm": "onnxruntime-web/dist/ort-wasm-simd-threaded.wasm",
};
export function voiceAssets() {
  const { dependencies } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url)));
  // Every /assets URL is immutable; a dependency upgrade must change its URL.
  const base = `/assets/voice-${dependencies["@ricky0123/vad-web"]}-${dependencies["onnxruntime-web"]}/`;

  const bytes = (source) => readFileSync(new URL(`./node_modules/${source}`, import.meta.url));
  return {
    name: "partyline-voice-assets",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: `${base.slice(1)}LICENSE.txt`,
        source: readFileSync(new URL("../docs/voice-third-party.txt", import.meta.url)),
      });
      for (const [name, source] of Object.entries(files)) {
        this.emitFile({ type: "asset", fileName: `${base.slice(1)}${name}`, source: bytes(source) });
      }
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split("?")[0];
        if (!path?.startsWith(base)) return next();
        const name = path.slice(base.length);
        const source = files[name];
        if (!source) return next();
        res.setHeader(
          "Content-Type",
          name.endsWith(".wasm")
            ? "application/wasm"
            : name.endsWith(".onnx")
              ? "application/octet-stream"
              : "text/javascript",
        );
        res.end(bytes(source));
      });
    },
  };
}
