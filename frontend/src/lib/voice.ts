/** Pure rules for voice input: support guards, take limits, caret insertion. */

export const MAX_TAKE_MS = 5 * 60 * 1000;

const MIME_PREFERENCE = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
] as const;

export interface VoiceEnvironment {
  isSecureContext: boolean;
  hasMediaDevices: boolean;
  hasRecorder: boolean;
}

/** Why the mic cannot work here, or null when it can. */
export function voiceUnsupported(env: VoiceEnvironment): string | null {
  if (!env.isSecureContext) {
    return "voice input needs HTTPS (or localhost): this page is not a secure context";
  }
  if (!env.hasMediaDevices || !env.hasRecorder) {
    return "this browser cannot record audio";
  }
  return null;
}

/** The first container the browser can record, or undefined to let it choose. */
export function pickMimeType(isSupported: (type: string) => boolean): string | undefined {
  return MIME_PREFERENCE.find((type) => isSupported(type));
}

/** A short, human reason for a failed getUserMedia call. */
export function describeMicError(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "microphone permission was denied; allow it in the browser's site settings";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "no microphone was found";
  }
  if (name === "NotReadableError" || name === "AbortError") {
    return "the microphone is busy or unavailable";
  }
  return "could not start the microphone";
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const seconds = String(total % 60).padStart(2, "0");
  return `${String(Math.floor(total / 60))}:${seconds}`;
}

/** Put a transcript at the caret (replacing any selection), spaced from its neighbours. */
export function insertAtCursor(
  text: string,
  start: number,
  end: number,
  insert: string,
): { value: string; caret: number } {
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  const spoken = insert.trim();
  const before = text.slice(0, from);
  const after = text.slice(to);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const tail = after && !/^\s/.test(after) ? " " : "";
  const value = `${before}${lead}${spoken}${tail}${after}`;
  return { value, caret: before.length + lead.length + spoken.length };
}

export interface PresetChoice {
  name: string;
  available: boolean;
}

/** The remembered preset if it still works, else the server default, else the first that works. */
export function choosePreset(
  presets: readonly PresetChoice[],
  saved: string | null,
  fallback: string,
): string | null {
  const usable = (name: string | null): string | null =>
    name !== null && presets.some((preset) => preset.name === name && preset.available) ? name : null;
  return usable(saved) ?? usable(fallback) ?? presets.find((preset) => preset.available)?.name ?? null;
}

const PRESET_KEY = "partyline.voice.preset";

/** Per-browser memory of the chosen preset; storage may be blocked, so both ends are guarded. */
export function readSavedPreset(): string | null {
  try {
    return localStorage.getItem(PRESET_KEY);
  } catch {
    return null;
  }
}

export function savePreset(name: string): void {
  try {
    localStorage.setItem(PRESET_KEY, name);
  } catch {
    // remembering the choice is a convenience only
  }
}

/** Back to the server default. */
export function clearSavedPreset(): void {
  try {
    localStorage.removeItem(PRESET_KEY);
  } catch {
    // as above
  }
}

/** What the composer's mic reports: a take in progress, and whether Dictate can start now. */
export interface VoiceStatus {
  busy: boolean;
  blocked: boolean;
  label: string;
}
