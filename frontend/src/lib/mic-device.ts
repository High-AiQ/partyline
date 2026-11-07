/**
 * Which microphone to use: the per-browser choice, the getUserMedia constraint
 * built from it, the fallback to the default device when it is gone, and the
 * device list for the picker.
 */

const MIC_KEY = "partyline.voice.mic";

/** The remembered device id, or null for the system default. Storage may throw (private mode). */
export function readSavedMic(): string | null {
  try {
    const saved = localStorage.getItem(MIC_KEY);
    if (!saved) return null;
    return saved;
  } catch {
    return null;
  }
}

export const MIC_CHANGED = "partyline-mic-changed";

export function saveMic(deviceId: string): void {
  try {
    localStorage.setItem(MIC_KEY, deviceId);
    window.dispatchEvent(new Event(MIC_CHANGED));
  } catch {
    // remembering the choice is a convenience only
  }
}

/** Back to the system default. */
export function clearSavedMic(): void {
  try {
    localStorage.removeItem(MIC_KEY);
    window.dispatchEvent(new Event(MIC_CHANGED));
  } catch {
    // as above
  }
}

export function micConstraints(deviceId: string | null): MediaStreamConstraints {
  return { audio: deviceId ? { deviceId: { exact: deviceId } } : true };
}

/** The chosen device is unplugged or renamed: the browser says so with one of these. */
export function isDeviceGone(error: unknown): boolean {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  return name === "OverconstrainedError" || name === "NotFoundError";
}

export const FALLBACK_NOTICE = "The selected microphone is not available; using the default one.";

/**
 * Open the chosen mic. A missing device falls back to the default one (`fellBack`);
 * a refusal or any other failure is thrown as is.
 */
export async function openMicStream(
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>,
  deviceId: string | null,
): Promise<{ stream: MediaStream; fellBack: boolean }> {
  try {
    return { stream: await getUserMedia(micConstraints(deviceId)), fellBack: false };
  } catch (error) {
    if (!deviceId || !isDeviceGone(error)) throw error;
    return { stream: await getUserMedia(micConstraints(null)), fellBack: true };
  }
}

export interface MicChoice {
  id: string;
  label: string;
}

export interface MicListing {
  mics: MicChoice[];
  /** The browser hides names until the page has had mic permission. */
  labelsHidden: boolean;
}

export function listMics(devices: readonly MediaDeviceInfo[]): MicListing {
  const inputs = devices.filter((device) => device.kind === "audioinput");
  return {
    mics: inputs.map((device, index) => ({
      id: device.deviceId,
      label: device.label === "" ? `Microphone ${String(index + 1)}` : device.label,
    })),
    labelsHidden: inputs.length > 0 && inputs.every((device) => !device.label),
  };
}

/** The name the browser gives the live track (empty when it hides it). */
export function streamMicLabel(stream: MediaStream): string | null {
  const label = stream.getTracks()[0]?.label;
  if (!label) return null;
  return label;
}
