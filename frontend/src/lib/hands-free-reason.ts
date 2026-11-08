import type { VoicePresets } from "../state/voice-presets.svelte.js";

/**
 * Why hands-free voice cannot listen right now, or "" when it can. The row
 * button and the phone composer's menu both disable on this, so they agree.
 */
export function handsFreeReason(
  voice: Pick<VoicePresets, "listing" | "error" | "active">,
  hasLiveProcess: boolean,
): string {
  const secure = typeof window !== "undefined" && window.isSecureContext && Boolean(navigator.mediaDevices);
  if (!secure) return "Hands-free voice needs HTTPS and microphone access.";
  if (!voice.listing) return voice.error ?? "Checking speech recognizers…";
  if (!voice.active) return "No speech recognizer is available.";
  if (!hasLiveProcess) return "Attach a process to use hands-free voice.";
  return "";
}
