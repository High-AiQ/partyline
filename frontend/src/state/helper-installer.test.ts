import { afterEach, describe, expect, it, vi } from "vitest";
import { screenApi } from "../lib/screen-api";
import { helperInstaller } from "./helper-installer.svelte.js";

const INSTALLER = {
  version: "1.2.0",
  filename: "PartylineHelper-Setup-1.2.0.exe",
  releases_url: "https://github.com/High-AiQ/partyline/releases",
  url: "https://github.com/High-AiQ/partyline/releases/download/helper-v1.2.0/PartylineHelper-Setup-1.2.0.exe",
};

afterEach(() => {
  helperInstaller.info = null;
  vi.restoreAllMocks();
});

describe("helper installer link", () => {
  it("is the server's exact-version GitHub release URL and is asked for once", async () => {
    const installer = vi.spyOn(screenApi, "installer").mockResolvedValue(INSTALLER);
    await Promise.all([helperInstaller.ensure(), helperInstaller.ensure()]);
    await helperInstaller.ensure();
    expect(installer).toHaveBeenCalledTimes(1);
    const url = new URL(helperInstaller.info?.url ?? "");
    expect(url.protocol).toBe("https:");
    expect(url.hostname).toBe("github.com");
    expect(url.pathname).toBe(
      "/High-AiQ/partyline/releases/download/helper-v1.2.0/PartylineHelper-Setup-1.2.0.exe",
    );
    expect(url.pathname).not.toContain("latest");
  });

  it("stays empty after a failed lookup and tries again on the next call", async () => {
    const installer = vi.spyOn(screenApi, "installer").mockRejectedValueOnce(new Error("down"));
    await helperInstaller.ensure();
    expect(helperInstaller.info).toBeNull();
    installer.mockResolvedValue(INSTALLER);
    await helperInstaller.ensure();
    expect(helperInstaller.info?.version).toBe("1.2.0");
  });
});
