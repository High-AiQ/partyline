import { describe, expect, it } from "vitest";
import { HELPER_WINDOWS_INSTALLER_URL, onWindows } from "./helper-installer";

describe("Windows installer link", () => {
  it("is a GitHub release URL, never a local address", () => {
    const url = new URL(HELPER_WINDOWS_INSTALLER_URL);
    expect(url.protocol).toBe("https:");
    expect(url.hostname).toBe("github.com");
    expect(url.pathname).toBe("/High-AiQ/partyline/releases/latest/download/PartylineHelper-Setup.exe");
    expect(HELPER_WINDOWS_INSTALLER_URL).not.toMatch(/localhost|127\.0\.0\.1|0\.0\.0\.0/);
  });

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
