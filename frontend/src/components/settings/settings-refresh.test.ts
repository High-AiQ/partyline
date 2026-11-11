/**
 * Settings never drops work: a search or a tab switch keeps unsaved drafts,
 * and the voice tab follows preset changes made elsewhere.
 */
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SettingsDialog from "../dialogs/SettingsDialog.svelte";
import VoiceSection from "./sections/VoiceSection.svelte";
import * as settingsApi from "../../lib/settings-api";
import type { AsrPreset, AsrSettings } from "../../lib/asr-api";
import { settingsNav } from "../../state/settings-nav.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";

let mounted: ReturnType<typeof mount> | null = null;
async function settle(): Promise<void> {
  for (let turn = 0; turn < 25; turn++) await tick();
}
function type(selector: string, value: string): void {
  const input = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector);
  if (!input) throw new Error(`missing ${selector}`);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}
beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(Element.prototype, "scrollIntoView", { value: vi.fn(), configurable: true });
  Object.defineProperty(Element.prototype, "scrollTo", { value: vi.fn(), configurable: true });
});
afterEach(async () => {
  if (mounted) await unmount(mounted);
  mounted = null;
  settingsNav.close();
  voicePresets.reset();
  vi.restoreAllMocks();
  vi.useRealTimers();
  document.body.replaceChildren();
});

it("keeps unsaved prose when search is entered and cleared", async () => {
  vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "saved prose" });
  settingsNav.show("general");
  mounted = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
  await settle();
  type("#globalProse", "my unsaved edits");
  expect(document.body.textContent).toContain("unsaved changes");
  type("#settingsSearch", "theme");
  await settle();
  type("#settingsSearch", "");
  await settle();
  expect(document.querySelector<HTMLTextAreaElement>("#globalProse")?.value).toBe("my unsaved edits");
});

it("keeps unsaved prose across a switch to another tab and back", async () => {
  vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "saved prose" });
  settingsNav.show("general");
  mounted = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
  await settle();
  type("#globalProse", "half written");
  settingsNav.show("appearance");
  await settle();
  expect(document.querySelector("#globalProse")?.closest("[hidden]")).not.toBeNull();
  settingsNav.show("general");
  await settle();
  expect(document.querySelector<HTMLTextAreaElement>("#globalProse")?.value).toBe("half written");
  expect(document.querySelector("#globalProse")?.closest("[hidden]")).toBeNull();
});

it("refreshes the open mic selector after the live event refreshes presets", async () => {
  const old: AsrPreset = {
    name: "old",
    kind: "command",
    source: "database",
    editable: true,
    overrides_config: false,
    is_default: true,
    can_be_default: true,
    available: true,
    fields: { argv: ["asr", "{audio}"] },
  };
  const initial: AsrSettings = { default: "old", presets: [old] };
  const next: AsrSettings = {
    default: "old",
    presets: [old, { ...old, name: "added-elsewhere", is_default: false }],
  };
  voicePresets.receive(initial);
  mounted = mount(VoiceSection, { target: document.body });
  await settle();

  // This is the action dispatched by asr_presets_changed and by reconnect.
  voicePresets.receive(next);
  await settle();
  expect(voicePresets.listing?.presets.map((preset) => preset.name)).toContain("added-elsewhere");
  const options = [...document.querySelectorAll<HTMLOptionElement>("#voiceMicPreset option")].map(
    (option) => option.value,
  );
  expect(options).toContain("added-elsewhere");
});
