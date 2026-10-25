import { describe, expect, it } from "vitest";
import { FileRefSchema } from "./contracts";
import type { FileRef } from "./contracts";
import { isModelFile, modelFormat } from "./model-files";

function file(kind: FileRef["kind"], filename: string | null, mime: string): FileRef {
  return {
    id: "model-1",
    kind,
    filename,
    title: null,
    description: null,
    mime,
    bytes: 100,
    width: null,
    height: null,
    thumb: null,
    slim: null,
    urls: { original: "/api/media/model-1/original", thumb: "", slim: null },
  };
}

describe("model attachment detection", () => {
  it("recognizes canonical MIME types and the model wire kind", () => {
    const glb = file("model", "shape.glb", "model/gltf-binary");
    const gltf = file("model", "shape.gltf", "model/gltf+json");
    expect(modelFormat(glb)).toBe("glb");
    expect(modelFormat(gltf)).toBe("gltf");
    expect(FileRefSchema.parse(glb).kind).toBe("model");
  });

  it("recognizes extension fallbacks case-insensitively for older uploads", () => {
    expect(modelFormat(file("file", "CUBE.GLB", "application/octet-stream"))).toBe("glb");
    expect(isModelFile(file("file", "scene.GLTF", "application/octet-stream"))).toBe(true);
  });

  it("does not infer a model from titles, URLs, or unrelated files", () => {
    expect(modelFormat(file("file", null, "model/gltf-binary"))).toBe("glb");
    expect(isModelFile(file("file", null, "application/octet-stream"))).toBe(false);
    expect(isModelFile(file("file", "notes.txt", "text/plain"))).toBe(false);
  });
});
