import { describe, expect, it } from "vitest";
import { onWindows } from "./helper-installer";

describe("Windows detection", () => {
  it("detects Windows from client hints first, then the user agent", () => {
    expect(onWindows({ userAgent: "x", userAgentData: { platform: "Windows" } })).toBe(true);
    expect(onWindows({ userAgent: "Windows NT", userAgentData: { platform: "macOS" } })).toBe(false);
    expect(onWindows({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130" })).toBe(true);
    expect(onWindows({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)" })).toBe(false);
    expect(onWindows({ userAgent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/130" })).toBe(false);
    expect(
      onWindows({ userAgent: "Mozilla/5.0 (Linux; Android 14) Windows Phone".replace("Windows", "Win") }),
    ).toBe(false);
  });
});
