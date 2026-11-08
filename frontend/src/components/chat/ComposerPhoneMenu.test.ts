import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import Composer from "./Composer.svelte";
import { layout } from "../../state/layout.svelte.js";
import { room } from "../../state/room.svelte.js";
import { handsFree } from "../../state/hands-free.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import type { Attachment } from "../../lib/contracts";

const line = {
  id: "phone-line",
  name: "Phone line",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 0,
};
const live: Attachment = {
  id: "phone-worker",
  conv_id: "phone-line",
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
  layout.narrow = false;
  voicePresets.reset();
  voicePresets.choose(null);
  handsFree.update({ enabled: false });
  room.leave({ clearRoute: false });
  room.attachments = [];
  document.body.replaceChildren();
});

/** A secure page with a recognizer and a live process, and a microphone that never answers. */
function readyForVoice(): void {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("MediaRecorder", { isTypeSupported: () => true });
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: () => new Promise(() => undefined) },
    configurable: true,
  });
  voicePresets.listing = { default: "asr", presets: [{ name: "asr", kind: "command", available: true }] };
  room.conversation = line;
  room.attachments = [live];
}

function trigger(): HTMLButtonElement | null {
  return document.querySelector<HTMLButtonElement>("[data-composer-more]");
}

function menuItem(name: string): HTMLButtonElement {
  const found = [
    ...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"], [role="menuitemcheckbox"]'),
  ].find((element) => element.textContent.trim().startsWith(name));
  if (!found) throw new Error(`Missing menu item ${name}`);
  return found;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}

it("on a phone the attach, mic and hands-free controls collapse into one menu button", async () => {
  layout.narrow = true;
  readyForVoice();
  const component = mount(Composer, { target: document.body });
  try {
    await settle();
    expect(document.querySelectorAll("[data-composer-more]")).toHaveLength(1);
    expect(document.querySelector("button.attach")).toBeNull();
    expect(document.querySelector("button.voice")).toBeNull();
    expect(document.querySelector("button.hands-free")).toBeNull();
  } finally {
    await unmount(component);
  }
});

it("on desktop the three icons stay in the row and there is no menu", async () => {
  layout.narrow = false;
  readyForVoice();
  const component = mount(Composer, { target: document.body });
  try {
    await settle();
    expect(document.querySelector("button.attach")).not.toBeNull();
    expect(document.querySelector("button.voice")).not.toBeNull();
    expect(document.querySelector("button.hands-free")).not.toBeNull();
    expect(trigger()).toBeNull();
  } finally {
    await unmount(component);
  }
});

it("dictation from the menu shows its live state in the row, and Cancel reaches the stop", async () => {
  layout.narrow = true;
  readyForVoice();
  const component = mount(Composer, { target: document.body });
  try {
    await settle();
    trigger()?.click();
    await settle();
    menuItem("Dictate").click();
    await settle();
    expect(trigger()).toBeNull();
    expect(document.querySelector("button.voice")).not.toBeNull();
    const cancel = document.querySelector<HTMLButtonElement>('button[aria-label="cancel voice message"]');
    expect(cancel).not.toBeNull();
    cancel?.click();
    await settle();
    expect(document.querySelector("button.voice-cancel")).toBeNull();
    expect(trigger()).not.toBeNull();
  } finally {
    await unmount(component);
  }
});

it("hands-free from the menu shows as the row's own button, and one tap turns it off", async () => {
  layout.narrow = true;
  readyForVoice();
  const component = mount(Composer, { target: document.body });
  try {
    await settle();
    trigger()?.click();
    await settle();
    menuItem("Hands-free").click();
    await settle();
    expect(handsFree.value.enabled).toBe(true);
    expect(trigger()).toBeNull();
    const active = document.querySelector<HTMLButtonElement>("button.hands-free");
    expect(active?.getAttribute("aria-pressed")).toBe("true");
    active?.click();
    await settle();
    expect(handsFree.value.enabled).toBe(false);
    expect(trigger()).not.toBeNull();
  } finally {
    await unmount(component);
  }
});

it("focus follows dictation: onto the live mic, Escape cancels it, and back to the menu", async () => {
  layout.narrow = true;
  readyForVoice();
  const component = mount(Composer, { target: document.body });
  try {
    await settle();
    const menuButton = trigger();
    menuButton?.click();
    await settle();
    menuItem("Dictate").click();
    await settle();
    const live = document.querySelector<HTMLButtonElement>("button.voice");
    expect(document.activeElement).toBe(live);
    live?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    await settle();
    expect(document.querySelector("button.voice")).toBeNull();
    expect(document.activeElement).toBe(trigger());
  } finally {
    await unmount(component);
  }
});

it("focus follows hands-free: onto its live button, and back to the menu when it turns off", async () => {
  layout.narrow = true;
  readyForVoice();
  const component = mount(Composer, { target: document.body });
  try {
    await settle();
    trigger()?.click();
    await settle();
    menuItem("Hands-free").click();
    await settle();
    const active = document.querySelector<HTMLButtonElement>("button.hands-free");
    expect(document.activeElement).toBe(active);
    active?.click();
    await settle();
    expect(document.activeElement).toBe(trigger());
  } finally {
    await unmount(component);
  }
});
