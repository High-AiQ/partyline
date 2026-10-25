import type { FileRef } from "./contracts";

export type ModelFormat = "glb" | "gltf";

type ModelFile = Pick<FileRef, "kind" | "filename" | "mime">;

/** Recognize current model attachments and compatible pre-model-kind uploads. */
export function modelFormat(file: ModelFile): ModelFormat | null {
  const mime = file.mime.toLowerCase().split(";", 1)[0]?.trim();
  if (mime === "model/gltf-binary") return "glb";
  if (mime === "model/gltf+json") return "gltf";
  const name = file.filename?.toLowerCase() ?? "";
  if (name.endsWith(".glb")) return "glb";
  if (name.endsWith(".gltf")) return "gltf";
  return null;
}

export function isModelFile(file: ModelFile): boolean {
  return modelFormat(file) !== null;
}
