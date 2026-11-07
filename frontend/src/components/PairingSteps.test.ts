import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import PairingSteps from "./PairingSteps.svelte";

const UVX = "uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' partyline-helper";
const CHECKOUT = "uv run --extra helper partyline-helper";

function setClipboard(clipboard: unknown): void {
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
}

/** Drains the promise chains a click starts; no clock involved. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await tick();
}

function copyButton(name: string): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`);
  if (!button) throw new Error(`missing ${name}`);
  return button;
}

afterEach(() => {
  setClipboard(undefined);
  delete (document as { execCommand?: unknown }).execCommand;
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("PairingSteps", () => {
  it("says where to run the commands and renders both options", async () => {
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "http://192.168.1.5:8642", code: "ABC-123" },
    });
    await tick();
    const text = document.body.textContent.replace(/\s+/g, " ");
    expect(text).toContain("on the computer whose screen you want to share");
    expect(text).toContain("not on the Partyline server");
    expect(text).toContain("Python 3.11+");
    expect(text).toContain("Without a checkout (recommended)");
    expect(text).toContain("From a partyline checkout");
    expect(text).toContain(`${UVX} pair http://192.168.1.5:8642 ABC-123`);
    expect(text).toContain(`${UVX} run`);
    expect(text).toContain(`${CHECKOUT} pair http://192.168.1.5:8642 ABC-123`);
    expect(text).toContain(`${CHECKOUT} run`);
    expect(text).toContain("Keep the run terminal open");
    expect(text).toContain("Screen Recording");
    expect(text).toContain("not Wayland");
    expect(document.querySelectorAll("button")).toHaveLength(6);
    await unmount(component);
  });

  it("offers a one-click link to the installed helper and the one-time install commands", async () => {
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "http://192.168.1.5:8642", code: "ABCD1234" },
    });
    await tick();
    const link = document.querySelector<HTMLAnchorElement>("a[data-testid=pair-link]");
    expect(link?.textContent).toBe("Pair with installed helper");
    expect(link?.getAttribute("href")).toBe(
      "partyline://pair?server=http%3A%2F%2F192.168.1.5%3A8642&code=ABCD1234",
    );
    const text = document.body.textContent.replace(/\s+/g, " ");
    expect(text).toContain("First time? Run … partyline-helper install once");
    expect(text).toContain(`${UVX} install`);
    expect(text).toContain(`${CHECKOUT} install`);
    expect(text).toContain(`${UVX} pair http://192.168.1.5:8642 ABCD1234`);
    await unmount(component);
  });

  it("shows no pair link for a placeholder code (Settings)", async () => {
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "https://pl.example", code: "YOUR-CODE" },
    });
    await tick();
    expect(document.querySelector("a[data-testid=pair-link]")).toBeNull();
    expect(document.body.textContent).toContain("partyline-helper install");
    await unmount(component);
  });

  it("copies the install command", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "https://pl.example", code: "C" },
    });
    await tick();
    copyButton("Copy Without a checkout (recommended) install command").click();
    await settle();
    expect(writeText).toHaveBeenCalledWith(`${UVX} install`);
    copyButton("Copy From a partyline checkout install command").click();
    await settle();
    expect(writeText).toHaveBeenCalledWith(`${CHECKOUT} install`);
    await unmount(component);
  });

  it("copies each command through the async clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "https://pl.example", code: "C" },
    });
    await tick();
    copyButton("Copy From a partyline checkout run command").click();
    await settle();
    expect(writeText).toHaveBeenCalledWith(`${CHECKOUT} run`);

    copyButton("Copy Without a checkout (recommended) pairing command").click();
    await settle();
    expect(writeText).toHaveBeenCalledWith(`${UVX} pair https://pl.example C`);

    await settle();
    expect(document.body.textContent).toContain("copied ✓");

    await unmount(component);
  });

  it("uses the legacy copy path when the async clipboard is unavailable (plain-http LAN)", async () => {
    setClipboard(undefined);
    const exec = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "http://lan:1", code: "C" },
    });
    await tick();
    copyButton("Copy Without a checkout (recommended) run command").click();
    await settle();
    expect(document.body.textContent).toContain("copied ✓");

    expect(exec).toHaveBeenCalledWith("copy");
    await unmount(component);
  });

  it("selects the command and says to select manually when every copy path fails", async () => {
    setClipboard(undefined);
    Object.defineProperty(document, "execCommand", { value: () => false, configurable: true });
    const component = mount(PairingSteps, {
      target: document.body,
      props: { origin: "http://lan:1", code: "C" },
    });
    await tick();
    copyButton("Copy From a partyline checkout pairing command").click();
    await settle();
    expect(document.body.textContent).toContain("copy failed; select manually");

    expect(window.getSelection()?.toString()).toBe(`${CHECKOUT} pair http://lan:1 C`);
    await unmount(component);
  });

  it("offers the installer only to a visitor on Windows, with the SmartScreen steps", async () => {
    const agent = vi.spyOn(navigator, "userAgent", "get");
    agent.mockReturnValue("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130");
    const windows = mount(PairingSteps, {
      target: document.body,
      props: { origin: "http://lan:1", code: "ABCDEF12" },
    });
    await tick();
    const link = document.querySelector<HTMLAnchorElement>("[data-testid=download-windows]");
    expect(link?.textContent).toBe("Download for Windows");
    expect(link?.href).toBe(
      "https://github.com/High-AiQ/partyline/releases/latest/download/PartylineHelper-Setup.exe",
    );
    const text = document.body.textContent.replace(/\s+/g, " ");
    expect(text).toContain("More info");
    expect(text).toContain("Run anyway");
    expect(text).toContain("no administrator rights");
    expect(text).toContain(`${UVX} run`); // the terminal path stays documented
    await unmount(windows);
    document.body.replaceChildren();
    agent.mockReturnValue("Mozilla/5.0 (X11; Linux x86_64) Firefox/130");
    const linux = mount(PairingSteps, {
      target: document.body,
      props: { origin: "http://lan:1", code: "C" },
    });
    await tick();
    expect(document.querySelector("[data-testid=download-windows]")).toBeNull();
    expect(document.querySelector("[data-testid=windows-installer]")).toBeNull();
    await unmount(linux);
  });
});
