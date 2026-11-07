import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearSavedMic,
  isDeviceGone,
  listMics,
  micConstraints,
  openMicStream,
  readSavedMic,
  saveMic,
  streamMicLabel,
} from "./mic-device";
import { fakeMicStream, gone } from "./mic-fakes";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("the saved mic choice", () => {
  it("round-trips through localStorage and clears back to the default", () => {
    expect(readSavedMic()).toBeNull();
    saveMic("abc");
    expect(readSavedMic()).toBe("abc");
    clearSavedMic();
    expect(readSavedMic()).toBeNull();
  });

  it("survives storage that throws, as in private mode", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    vi.stubGlobal("localStorage", blocked);
    expect(readSavedMic()).toBeNull();
    expect(() => {
      saveMic("abc");
      clearSavedMic();
    }).not.toThrow();
  });
});

describe("micConstraints", () => {
  it("asks for an exact device when one is chosen", () => {
    expect(micConstraints("abc")).toEqual({ audio: { deviceId: { exact: "abc" } } });
  });
  it("asks for any mic otherwise", () => {
    expect(micConstraints(null)).toEqual({ audio: true });
  });
});

describe("openMicStream", () => {
  it("passes the chosen device through", async () => {
    const { stream } = fakeMicStream();
    const getUserMedia = vi.fn(() => Promise.resolve(stream));
    await expect(openMicStream(getUserMedia, "abc")).resolves.toEqual({ stream, fellBack: false });
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "abc" } } });
  });

  it.each(["OverconstrainedError", "NotFoundError"] as const)(
    "falls back to the default device on %s",
    async (name) => {
      const { stream } = fakeMicStream();
      const getUserMedia = vi
        .fn<(c: MediaStreamConstraints) => Promise<MediaStream>>()
        .mockRejectedValueOnce(gone(name))
        .mockResolvedValueOnce(stream);
      await expect(openMicStream(getUserMedia, "abc")).resolves.toEqual({ stream, fellBack: true });
      expect(getUserMedia).toHaveBeenLastCalledWith({ audio: true });
    },
  );

  it("does not retry a refused permission", async () => {
    const getUserMedia = vi.fn(() => Promise.reject(gone("NotAllowedError")));
    await expect(openMicStream(getUserMedia, "abc")).rejects.toThrow();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("does not retry when the default device itself is missing", async () => {
    const getUserMedia = vi.fn(() => Promise.reject(gone("NotFoundError")));
    await expect(openMicStream(getUserMedia, null)).rejects.toThrow();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("recognises both names and nothing else", () => {
    expect(isDeviceGone(gone("NotFoundError"))).toBe(true);
    expect(isDeviceGone(gone("OverconstrainedError"))).toBe(true);
    expect(isDeviceGone(gone("NotAllowedError"))).toBe(false);
    expect(isDeviceGone("x")).toBe(false);
  });
});

function info(kind: string, deviceId: string, label: string): MediaDeviceInfo {
  return { kind, deviceId, label } as MediaDeviceInfo;
}

describe("listMics", () => {
  it("lists only inputs, by their names", () => {
    const listing = listMics([
      info("audioinput", "a", "Headset (Jabra)"),
      info("videoinput", "v", "Camera"),
      info("audiooutput", "o", "Speakers"),
    ]);
    expect(listing).toEqual({ mics: [{ id: "a", label: "Headset (Jabra)" }], labelsHidden: false });
  });

  it("flags hidden names and numbers the inputs", () => {
    const listing = listMics([info("audioinput", "a", ""), info("audioinput", "b", "")]);
    expect(listing.labelsHidden).toBe(true);
    expect(listing.mics.map((mic) => mic.label)).toEqual(["Microphone 1", "Microphone 2"]);
  });

  it("does not ask for permission when there is no input at all", () => {
    expect(listMics([]).labelsHidden).toBe(false);
  });
});

describe("streamMicLabel", () => {
  it("names the first track, or nothing", () => {
    expect(streamMicLabel(fakeMicStream("Jabra").stream)).toBe("Jabra");
    expect(streamMicLabel({ getTracks: () => [] } as unknown as MediaStream)).toBeNull();
  });
});
