import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import ComposerMoreMenu from "./ComposerMoreMenu.svelte";
import { handsFree } from "../../state/hands-free.svelte.js";
import { room } from "../../state/room.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { walkthrough } from "../../state/walkthrough.svelte.js";
import type { Attachment } from "../../lib/contracts";

function required<T>(value: T | null | undefined): T {
  if (value == null) throw new Error("Missing control");
  return value;
}

const line = {
  id: "menu-line",
  name: "Menu line",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 0,
};
const live: Attachment = {
  id: "menu-worker",
  conv_id: "menu-line",
  name: "sol",
  adapter: "fake",
  command: ["fake"],
  cwd: "/tmp",
  status: "running",
  last_seen: 0,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
  voicePresets.reset();
  voicePresets.choose(null);
  handsFree.update({ enabled: false });
  room.conversation = null;
  room.attachments = [];
  walkthrough.active = false;
  document.body.replaceChildren();
});

/** A secure page with a recognizer and a live process: the only state in which hands-free can start. */
function readyForHandsFree(): void {
  vi.stubGlobal("isSecureContext", true);
  Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
  voicePresets.listing = { default: "asr", presets: [{ name: "asr", kind: "command", available: true }] };
  room.conversation = line;
  room.attachments = [live];
}

function mountMenu(props: { attachDisabled?: boolean; dictateBlocked?: boolean } = {}) {
  const onattach = vi.fn();
  const ondictate = vi.fn();
  const component = mount(ComposerMoreMenu, {
    target: document.body,
    props: {
      attachDisabled: props.attachDisabled ?? false,
      dictateBlocked: props.dictateBlocked ?? false,
      dictateLabel: "record a voice message",
      onattach,
      ondictate,
    },
  });
  const trigger = required(document.querySelector<HTMLButtonElement>("[data-composer-more]"));
  return { component, onattach, ondictate, trigger };
}

function items(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"], [role="menuitemcheckbox"]')];
}

function item(start: string): HTMLButtonElement {
  return required(items().find((element) => element.textContent.trim().startsWith(start)));
}

async function open(trigger: HTMLButtonElement): Promise<void> {
  trigger.click();
  await tick();
  await tick();
}

it("is one labelled button that opens a three-item menu", async () => {
  const { component, trigger } = mountMenu();
  expect(trigger.getAttribute("aria-label")).toBe("More: attach, dictate, hands-free");
  expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  await open(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(items().map((element) => element.getAttribute("role"))).toEqual([
    "menuitem",
    "menuitem",
    "menuitemcheckbox",
  ]);
  expect(document.activeElement).toBe(item("Attach files"));
  await unmount(component);
});

it("runs each item's action, closes the menu and returns focus to the button", async () => {
  readyForHandsFree();
  const { component, onattach, ondictate, trigger } = mountMenu();
  await open(trigger);
  item("Attach files").click();
  await tick();
  expect(onattach).toHaveBeenCalledOnce();
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);

  await open(trigger);
  item("Dictate").click();
  expect(ondictate).toHaveBeenCalledOnce();

  await open(trigger);
  expect(item("Hands-free").getAttribute("aria-checked")).toBe("false");
  item("Hands-free").click();
  await tick();
  expect(handsFree.value.enabled).toBe(true);
  await open(trigger);
  expect(item("Hands-free").getAttribute("aria-checked")).toBe("true");
  expect(item("Hands-free").textContent).toContain("on");
  await unmount(component);
});

it("keeps disabled items inert: no attach, no dictate, no hands-free without a line", async () => {
  const { component, onattach, ondictate, trigger } = mountMenu({
    attachDisabled: true,
    dictateBlocked: true,
  });
  await open(trigger);
  expect(item("Attach files").getAttribute("aria-disabled")).toBe("true");
  item("Attach files").click();
  item("Dictate").click();
  item("Hands-free").click();
  expect(onattach).not.toHaveBeenCalled();
  expect(ondictate).not.toHaveBeenCalled();
  expect(handsFree.value.enabled).toBe(false);
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  await unmount(component);
});

it("moves with the arrow keys, closes on Escape, an outside tap or Tab, and returns focus", async () => {
  const { component, trigger } = mountMenu();
  await tick();
  trigger.focus();
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
  await tick();
  await tick();
  expect(document.activeElement).toBe(item("Attach files"));
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
  expect(document.activeElement).toBe(item("Dictate"));
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp" }));
  expect(document.activeElement).toBe(item("Attach files"));
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp" }));
  expect(document.activeElement).toBe(item("Hands-free"));

  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  await tick();
  expect(document.activeElement).toBe(trigger);
  expect(document.querySelector('[role="menu"]')).toBeNull();

  await open(trigger);
  document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
  await tick();
  expect(document.querySelector('[role="menu"]')).toBeNull();

  await open(trigger);
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab" }));
  await tick();
  expect(document.querySelector('[role="menu"]')).toBeNull();
  await unmount(component);
});

it("offers only attach while a walkthrough is recording", async () => {
  walkthrough.active = true;
  const { component, trigger } = mountMenu();
  await open(trigger);
  expect(items().map((element) => element.textContent.trim())).toEqual(["Attach files…"]);
  await unmount(component);
});
