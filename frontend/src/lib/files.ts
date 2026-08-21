import { requestBlob } from "./http";
import type { ChatMessage, FileRef } from "./contracts";

export const MAX_FILES_PER_MESSAGE = 6;

export interface PendingFiles {
  files: File[];
  title: string;
  description: string;
}

export interface FileIntake {
  generation: number;
  files: File[];
}

/** The durable digest lines an agent reads, one per file, by kind prefix. */
const DIGEST_PREFIXES = ["📷 ", "🎵 ", "🎬 ", "📎 "];

/** Agent-facing file metadata rides in the durable body but not the human UI.
 *  The server appends exactly one digest line per file, so the strip is
 *  bounded: a real sentence that happens to start with a prefix survives. */
export function visibleMessageBody(message: ChatMessage): string {
  if (!message.files.length) return message.body;
  const lines = message.body.split("\n");
  let end = lines.length;
  let digests = message.files.length;
  while (end > 0 && digests > 0 && DIGEST_PREFIXES.some((prefix) => lines[end - 1]?.startsWith(prefix))) {
    end--;
    digests--;
  }
  return lines.slice(0, end).join("\n").trimEnd();
}

export function fileLabel(file: FileRef, position: number): string {
  return file.filename ?? file.description ?? file.title ?? `shared file ${String(position + 1)}`;
}

export function humanSize(bytes: number): string {
  let size = bytes;
  let unit = "B";
  for (const next of ["KB", "MB", "GB"]) {
    if (size < 1000) break;
    size /= 1000;
    unit = next;
  }
  return unit === "B" ? `${String(size)} B` : `${size.toFixed(1)} ${unit}`;
}

/** Save the original bytes under their uploaded name without a tokened URL. */
export async function downloadFile(file: FileRef): Promise<void> {
  const blob = await requestBlob(file.urls.original);
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const extension = file.mime.split("/")[1]?.split("+")[0] ?? "bin";
  const stem = (file.title ?? file.id).replace(/[^A-Za-z0-9_.-]+/g, "-");
  link.href = objectUrl;
  link.download = file.filename ?? `${stem}.${extension}`;
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(objectUrl);
  }, 60_000);
}
