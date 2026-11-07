import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsDialog from "./SettingsDialog.svelte";
import SettingsRoute from "../settings/SettingsRoute.svelte";
import * as settingsApi from "../../lib/settings-api";
import { aboutApi } from "../../lib/about-api";
import { SAVED_FLASH_MS } from "../../lib/save-state";
import { dialogs } from "../../state/dialogs.svelte.js";
import { settingsNav } from "../../state/settings-nav.svelte.js";
import { theme } from "../../state/theme.svelte.js";

async function settle(): Promise<void> {
  for (let turn = 0; turn < 20; turn++) await tick();
}

function go(hash: string): void {
  history.pushState({}, "", `/${hash}`);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  flushSync();
}

/** The shown tab's heading; tabs opened earlier stay mounted but hidden. */
function heading(): string {
  return document.querySelector("div:not([hidden]) > section h2")?.textContent.trim() ?? "";
}

function current(): string | null | undefined {
  return document.querySelector('nav a[aria-current="page"]')?.getAttribute("data-section");
}

beforeEach(() => {
  Object.defineProperty(Element.prototype, "scrollIntoView", { value: vi.fn(), configurable: true });
  Object.defineProperty(Element.prototype, "scrollTo", { value: vi.fn(), configurable: true });
  vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "be kind" });
  vi.spyOn(aboutApi, "about").mockResolvedValue({
    version: "2.81.0",
    build: "abc",
    instance_name: "lab",
    checkout_path: "/srv/partyline",
    git_head: "0123456789abcdef",
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  dialogs.closeAll();
  settingsNav.close();
  history.replaceState({}, "", "/");
  document.body.replaceChildren();
});

describe("settings modal", () => {
  it("opens from a deep link on that tab, follows Back and Forward, and closes when the route leaves", async () => {
    history.replaceState({}, "", "/#/settings/about");
    settingsNav.sync();
    const route = mount(SettingsRoute, { target: document.body });
    flushSync();
    expect(dialogs.stack.map((entry) => entry.component)).toEqual([SettingsDialog]);
    const entry = dialogs.stack[0];
    if (!entry) throw new Error("no dialog");
    const dialog = mount(SettingsDialog, {
      target: document.body,
      props: { ...entry.props, close: vi.fn() },
    });
    await settle();
    expect(heading()).toBe("About");
    expect(current()).toBe("about");
    expect(document.querySelector('[data-about="git head"]')?.textContent).toBe("0123456789abcdef");
    go("#/settings/general");
    await settle();
    expect(heading()).toBe("General");
    expect(document.querySelector<HTMLTextAreaElement>("#globalProse")?.value).toBe("be kind");
    go("#/c/some-line");
    expect(settingsNav.section).toBeNull();
    expect(dialogs.stack).toEqual([]);
    await unmount(dialog);
    await unmount(route);
  });

  it("tab links are real links to each section's route", async () => {
    settingsNav.show("general");
    const dialog = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
    await settle();
    const links = [...document.querySelectorAll<HTMLAnchorElement>("nav a[data-section]")];
    expect(links.map((link) => link.getAttribute("href"))).toContain("#/settings/voice");
    expect(links).toHaveLength(9);
    expect(document.activeElement?.id).toBe("settings-heading-general");
    await unmount(dialog);
  });

  it("searches across every tab, counts matches per tab, and lands on the picked row", async () => {
    settingsNav.show("general");
    const dialog = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
    await settle();
    const search = document.querySelector<HTMLInputElement>("#settingsSearch");
    if (!search) throw new Error("no search");
    search.value = "theme";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    const results = [...document.querySelectorAll<HTMLButtonElement>(".search-result")];
    expect(results.map((result) => result.textContent)).toEqual([expect.stringContaining("Theme")]);
    expect(document.querySelector('[data-section="appearance"] [aria-label="1 matching"]')).not.toBeNull();
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await settle();
    expect(location.hash).toBe("#/settings/appearance");
    expect(document.getElementById("setting-theme")?.classList.contains("flash")).toBe(true);
    expect(document.activeElement?.getAttribute("name")).toBe("theme");
    expect(search.value).toBe("");
    search.value = "zzz";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(document.body.textContent).toContain("no settings match");
    // Escape in the search box clears it rather than closing settings.
    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    const outer = vi.fn();
    window.addEventListener("keydown", outer);
    search.dispatchEvent(escape);
    flushSync();
    window.removeEventListener("keydown", outer);
    expect(outer).not.toHaveBeenCalled();
    expect(search.value).toBe("");
    // `/` from elsewhere jumps back to search.
    document.body.focus();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "/", cancelable: true }));
    expect(document.activeElement).toBe(search);
    await unmount(dialog);
  });

  it("closing the modal any way leaves the settings route for the line it covered", async () => {
    history.replaceState({}, "", "/#/c/line-9");
    const route = mount(SettingsRoute, { target: document.body });
    settingsNav.show("about");
    flushSync();
    expect(dialogs.stack).toHaveLength(1);
    const close = vi.fn();
    const dialog = mount(SettingsDialog, {
      target: document.body,
      props: { close, ondismiss: dialogs.stack[0]?.props.ondismiss as () => void },
    });
    await settle();
    document.querySelector<HTMLButtonElement>('button[aria-label="close"]')?.click();
    expect(close).toHaveBeenCalled();
    await unmount(dialog);
    flushSync();
    expect(settingsNav.section).toBeNull();
    expect(location.hash).toBe("#/c/line-9");
    await unmount(route);
  });

  it("saves global prose explicitly and confirms it, then the confirmation fades", async () => {
    vi.useFakeTimers();
    const save = vi.spyOn(settingsApi, "setGlobalProse").mockResolvedValue({ value: "be brief" });
    settingsNav.show("general");
    const dialog = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
    await settle();
    const field = document.querySelector<HTMLTextAreaElement>("#globalProse");
    if (!field) throw new Error("no prose");
    field.value = "be brief";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(document.body.textContent).toContain("unsaved changes");
    document.querySelector<HTMLFormElement>("#globalProseForm")?.requestSubmit();
    await settle();
    expect(save).toHaveBeenCalledWith("be brief");
    expect(document.querySelector("[data-save-phase]")?.textContent).toContain("saved ✓");
    await vi.advanceTimersByTimeAsync(SAVED_FLASH_MS);
    expect(document.querySelector("[data-save-phase]")?.getAttribute("data-save-phase")).toBe("idle");
    await unmount(dialog);
  });

  it("switches the theme on change, including back to following the system", async () => {
    settingsNav.show("appearance");
    const dialog = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
    await settle();
    const radio = (value: string) =>
      document.querySelector<HTMLInputElement>(`input[name="theme"][value="${value}"]`);
    radio("light")?.click();
    await settle();
    expect(theme.current).toBe("light");
    expect(theme.explicit).toBe(true);
    radio("system")?.click();
    await settle();
    expect(theme.explicit).toBe(false);
    expect(radio("system")?.checked).toBe(true);
    expect(document.querySelector("[data-save-phase]")?.textContent).toContain("saved ✓");
    await unmount(dialog);
  });
});
