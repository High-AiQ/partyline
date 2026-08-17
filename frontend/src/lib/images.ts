import type { ChatMessage, ImageRef } from "./contracts";

export const MAX_IMAGES_PER_MESSAGE = 6;

export interface PendingImages {
  files: File[];
  title: string;
  description: string;
}

export interface ImageIntake {
  generation: number;
  files: File[];
}

/** Agent-facing image metadata rides in the durable body but not the human UI. */
export function visibleMessageBody(message: ChatMessage): string {
  if (!message.images.length) return message.body;
  const lines = message.body.split("\n");
  let end = lines.length;
  while (end > 0 && lines[end - 1]?.startsWith("📷 ")) end--;
  return lines.slice(0, end).join("\n").trimEnd();
}

export function imageLabel(image: ImageRef, position: number): string {
  return image.description ?? image.title ?? `shared image ${String(position + 1)}`;
}
