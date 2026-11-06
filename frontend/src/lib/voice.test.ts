import { describe, expect, it } from "vitest";
import {
  choosePreset,
  describeMicError,
  formatElapsed,
  insertAtCursor,
  pickMimeType,
  voiceUnsupported,
} from "./voice";

describe("voice guards", () => {
  it("explains an insecure context, a missing API, and passes otherwise", () => {
    const ok = { isSecureContext: true, hasMediaDevices: true, hasRecorder: true };
    expect(voiceUnsupported(ok)).toBeNull();
    expect(voiceUnsupported({ ...ok, isSecureContext: false })).toMatch(/HTTPS/);
    expect(voiceUnsupported({ ...ok, hasMediaDevices: false })).toMatch(/cannot record/);
    expect(voiceUnsupported({ ...ok, hasRecorder: false })).toMatch(/cannot record/);
  });

  it("maps microphone errors to short reasons", () => {
    expect(describeMicError(new DOMException("x", "NotAllowedError"))).toMatch(/denied/);
    expect(describeMicError(new DOMException("x", "NotFoundError"))).toMatch(/no microphone/);
    expect(describeMicError(new DOMException("x", "NotReadableError"))).toMatch(/busy/);
    expect(describeMicError("weird")).toMatch(/could not start/);
  });

  it("picks the first supported container", () => {
    expect(pickMimeType((t) => t === "audio/webm")).toBe("audio/webm");
    expect(pickMimeType(() => true)).toBe("audio/webm;codecs=opus");
    expect(pickMimeType(() => false)).toBeUndefined();
  });

  it("formats elapsed time", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(65_900)).toBe("1:05");
    expect(formatElapsed(-5)).toBe("0:00");
  });
});

describe("insertAtCursor", () => {
  it("inserts at the caret with spacing and reports the new caret", () => {
    expect(insertAtCursor("hello world", 5, 5, " big ")).toEqual({ value: "hello big world", caret: 9 });
    expect(insertAtCursor("", 0, 0, "hi")).toEqual({ value: "hi", caret: 2 });
    expect(insertAtCursor("ab", 1, 1, "x")).toEqual({ value: "a x b", caret: 3 });
  });
  it("replaces a selection and clamps wild offsets", () => {
    expect(insertAtCursor("one two three", 4, 7, "2")).toEqual({ value: "one 2 three", caret: 5 });
    expect(insertAtCursor("abc", 99, 120, "z").value).toBe("abc z");
  });
});

describe("choosePreset", () => {
  const list = [
    { name: "a", available: false },
    { name: "b", available: true },
    { name: "c", available: true },
  ];
  it("prefers the saved preset, then the default, then the first that works", () => {
    expect(choosePreset(list, "c", "b")).toBe("c");
    expect(choosePreset(list, "a", "c")).toBe("c");
    expect(choosePreset(list, "gone", "a")).toBe("b");
    expect(choosePreset([{ name: "a", available: false }], null, "a")).toBeNull();
  });
});
