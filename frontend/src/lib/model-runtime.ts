import type { FileRef } from "./contracts";
import { requestBlob } from "./http";
import { modelFormat } from "./model-files";
import type { Theme } from "./theme";

export interface ModelViewer {
  readonly setTheme: (theme: Theme) => void;
  readonly dispose: () => void;
}

export interface LoadModelOptions {
  container: HTMLDivElement;
  file: FileRef;
  theme: Theme;
}

/** The Three.js chunk and protected bytes are both deferred until this call. */
export async function loadModel({ container, file, theme }: LoadModelOptions): Promise<ModelViewer> {
  const format = modelFormat(file);
  if (!format) throw new Error("unsupported model format");
  const [engine, blob] = await Promise.all([import("./model-three"), requestBlob(file.urls.original)]);
  const data =
    format === "gltf" ? new TextDecoder().decode(await blob.arrayBuffer()) : await blob.arrayBuffer();
  return engine.createModelViewer(container, data, theme);
}
