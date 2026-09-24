/** Reliable send: chat always goes over REST; the wire carries events only. */

import type { ChatMessage } from "./contracts";
import { postMessage } from "./message-api";

export interface SayResult {
  ok: boolean;
  message?: ChatMessage;
  error?: string;
}

export async function sayOnLine(convId: string, body: string): Promise<SayResult> {
  const text = body.trim();
  if (!text) return { ok: false };
  try {
    return { ok: true, message: await postMessage(convId, text) };
  } catch (failure: unknown) {
    const error = failure instanceof Error ? failure.message : "could not send message";
    return { ok: false, error };
  }
}
