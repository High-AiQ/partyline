import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceSection from "./VoiceSection.svelte";
import { asrApi } from "../../../lib/asr-api";
import type { AsrPreset, AsrSettings } from "../../../lib/asr-api";
import { voicePresets } from "../../../state/voice-presets.svelte.js";

const base = {
  overrides_config: false,
  is_default: false,
  can_be_default: true,
  available: true,
  key_env: null,
  key_set: null,
} as const;
const local: AsrPreset = {
  ...base,
  name: "local",
  kind: "faster-whisper",
  source: "config",
  editable: false,
  is_default: true,
  fields: { model: "large-v3-turbo" },
};
const cloud: AsrPreset = {
  ...base,
  name: "cloud",
  kind: "openai-compatible",
  source: "database",
  editable: true,
  fields: { base_url: "https://api.openai.com", model: "whisper-1", api_key_env: "OPENAI_API_KEY" },
  key_env: "OPENAI_API_KEY",
  key_set: false,
  available: false,
  reason: "OPENAI_API_KEY is not set",
};
const second: AsrPreset = { ...cloud, name: "second", key_set: true, available: true, reason: null };
const LISTING: AsrSettings = { default: "local", presets: [cloud, second, local] };

async function settle(): Promise<void> {
  for (let turn = 0; turn < 25; turn++) await tick();
}

const maybeCard = (name: string) => document.querySelector<HTMLElement>(`[data-asr-preset="${name}"]`);
function card(name: string): HTMLElement {
  const found = maybeCard(name);
  if (!found) throw new Error(`no card ${name}`);
  return found;
}
const button = (root: ParentNode, text: string) =>
  [...root.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent.trim() === text);

function type(input: HTMLInputElement | HTMLTextAreaElement | null | undefined, value: string): void {
  if (!input) throw new Error("missing input");
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}

beforeEach(() => {
  voicePresets.receive(LISTING);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  voicePresets.reset();
  voicePresets.choose(null);
  document.body.replaceChildren();
});

describe("voice tab", () => {
  it("lists recognizers with their source, availability and key state, never a key", async () => {
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    expect(card("local").textContent).toContain("from config file");
    expect(card("local").textContent).toContain("default");
    expect(card("cloud").querySelector("[data-availability]")?.textContent).toContain(
      "OPENAI_API_KEY is not set",
    );
    expect(card("cloud").querySelector("[data-key-state]")?.textContent).toMatch(
      /OPENAI_API_KEY\s+is\s+not set/,
    );
    expect(card("second").querySelector("[data-key-state]")?.textContent).toMatch(/is\s+set/);
    // Config presets can be customized but not edited, moved or deleted in place.
    expect(button(card("local"), "customize")).toBeDefined();
    expect(button(card("local"), "delete")).toBeUndefined();
    expect(document.body.innerHTML).not.toMatch(/sk-/);
    await unmount(section);
  });

  it("chooses this browser's mic recognizer and says what the mic will use", async () => {
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    const select = document.querySelector<HTMLSelectElement>("#voiceMicPreset");
    if (!select) throw new Error("no mic choice");
    expect(document.body.textContent).toContain("the mic uses local");
    expect([...select.options].find((o) => o.value === "cloud")?.disabled).toBe(true);
    select.value = "second";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(voicePresets.chosen).toBe("second");
    expect(voicePresets.active).toBe("second");
    expect(localStorage.getItem("partyline.voice.preset")).toBe("second");
    select.value = "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(voicePresets.chosen).toBeNull();
    await unmount(section);
  });

  it("validates a new recognizer inline and adds it", async () => {
    const created: AsrSettings = { ...LISTING, presets: [...LISTING.presets, { ...second, name: "openai" }] };
    const create = vi.spyOn(asrApi, "create").mockResolvedValue(created);
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    button(document, "add recognizer…")?.click();
    flushSync();
    const form = document.querySelector<HTMLFormElement>("#setting-asr-add form");
    if (!form) throw new Error("no form");
    const inputs = () => [...form.querySelectorAll<HTMLInputElement>("input")];
    const byLabel = (label: string) =>
      inputs().find((input) => form.querySelector(`label[for="${input.id}"]`)?.textContent.trim() === label);
    expect(byLabel("model")?.value).toBe("gpt-transcribe");
    expect(byLabel("model")?.placeholder).toBe("gpt-transcribe");
    expect(form.textContent).toContain("use gpt-transcribe for OpenAI");
    const format = form.querySelector<HTMLSelectElement>("select:not([id$='kind'])");
    expect(format?.value).toBe("json");
    expect(format?.selectedOptions[0]?.textContent).toContain("transcript text");
    expect(format?.options[1]?.textContent).toContain("timed segments");
    type(byLabel("name"), "cloud");
    type(byLabel("API key variable"), "sk-proj-123");
    form.requestSubmit();
    await settle();
    expect(create).not.toHaveBeenCalled();
    expect(form.textContent).toContain("already has this name");
    expect(form.textContent).toContain("never the key itself");
    expect(document.activeElement).toBe(byLabel("name"));
    type(byLabel("name"), "openai");
    type(byLabel("API key variable"), "OPENAI_API_KEY");
    form.requestSubmit();
    await settle();
    expect(create).toHaveBeenCalledTimes(1);
    expect(create.mock.calls[0]?.[0]).toBe("openai");
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      kind: "openai-compatible",
      fields: { model: "gpt-transcribe", response_format: "json", api_key_env: "OPENAI_API_KEY" },
    });
    expect(maybeCard("openai")).not.toBeNull();
    expect(document.querySelector("#setting-asr-add form")).toBeNull();
    await unmount(section);
  });

  it("saves an OpenAI Whisper upgrade at once, keeping the other draft edits", async () => {
    const update = vi.spyOn(asrApi, "update").mockResolvedValue(LISTING);
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    button(card("cloud"), "edit")?.click();
    flushSync();
    const form = document.querySelector<HTMLFormElement>("#setting-asr-presets form");
    if (!form) throw new Error("no edit form");
    expect(form.querySelector<HTMLInputElement>("input[id$='model']")?.value).toBe("whisper-1");
    expect(form.querySelector<HTMLSelectElement>("select[id$='format']")?.value).toBe("verbose_json");
    type(form.querySelector<HTMLInputElement>("input[id$='language']"), "de");
    const migrate = button(form, "Switch to gpt-transcribe and save");
    expect(migrate).toBeDefined();
    migrate?.click();
    await settle();
    expect(update).toHaveBeenCalledOnce();
    expect(update.mock.calls[0]?.[0]).toBe("cloud");
    expect(update.mock.calls[0]?.[1].fields).toMatchObject({
      model: "gpt-transcribe",
      response_format: "json",
      language: "de",
      base_url: "https://api.openai.com",
      api_key_env: "OPENAI_API_KEY",
    });
    expect(document.querySelector("#setting-asr-presets form")).toBeNull();
    await unmount(section);
  });

  it("keeps the form and shows the refusal when the whisper switch fails to save", async () => {
    const update = vi.spyOn(asrApi, "update").mockRejectedValue(new Error("disk is full"));
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    button(card("cloud"), "edit")?.click();
    flushSync();
    button(document.body, "Switch to gpt-transcribe and save")?.click();
    await settle();
    expect(update).toHaveBeenCalledOnce();
    const form = document.querySelector<HTMLFormElement>("#setting-asr-presets form");
    expect(form?.textContent).toContain("disk is full");
    expect(form?.querySelector<HTMLInputElement>("input[id$='model']")?.value).toBe("gpt-transcribe");
    await unmount(section);
  });

  it("edits, reorders, makes default and deletes settings presets, showing a refusal", async () => {
    const update = vi.spyOn(asrApi, "update").mockResolvedValue(LISTING);
    const reorder = vi
      .spyOn(asrApi, "reorder")
      .mockResolvedValue({ ...LISTING, presets: [second, cloud, local] });
    const makeDefault = vi.spyOn(asrApi, "makeDefault").mockRejectedValue(new Error("not yet"));
    const remove = vi.spyOn(asrApi, "remove").mockResolvedValue({ ...LISTING, presets: [second, local] });
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    button(card("cloud"), "edit")?.click();
    flushSync();
    const form = document.querySelector<HTMLFormElement>("#setting-asr-presets form");
    if (!form) throw new Error("no edit form");
    form.requestSubmit();
    await settle();
    expect(update).toHaveBeenCalledWith("cloud", expect.objectContaining({ kind: "openai-compatible" }));
    document.querySelector<HTMLButtonElement>('[aria-label="move cloud down"]')?.click();
    await settle();
    expect(reorder).toHaveBeenCalledWith(["second", "cloud"]);
    expect(document.querySelector<HTMLButtonElement>('[aria-label="move second up"]')?.disabled).toBe(true);
    button(card("cloud"), "make default")?.click();
    await settle();
    expect(makeDefault).toHaveBeenCalledWith("cloud");
    expect(document.querySelector("#setting-asr-presets .line-status")?.textContent).toContain("not yet");
    button(card("cloud"), "delete")?.click();
    flushSync();
    button(card("cloud"), "yes, delete")?.click();
    await settle();
    expect(remove).toHaveBeenCalledWith("cloud");
    expect(maybeCard("cloud")).toBeNull();
    await unmount(section);
  });

  it("tests a recognizer with an uploaded file and shows transcript, language and latency", async () => {
    const test = vi.spyOn(asrApi, "test").mockResolvedValue({
      preset: "second",
      text: "hello there",
      language: "en",
      duration: 1.5,
      latency_ms: 420,
    });
    const section = mount(VoiceSection, { target: document.body });
    await settle();
    button(card("second"), "test")?.click();
    flushSync();
    const file = card("second").querySelector<HTMLInputElement>('input[type="file"]');
    if (!file) throw new Error("no file input");
    const audio = new File(["x"], "take.webm", { type: "audio/webm" });
    Object.defineProperty(file, "files", { value: [audio], configurable: true });
    file.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(test).toHaveBeenCalledWith("second", audio, expect.any(AbortSignal));
    const result = card("second").querySelector("[data-test-result]")?.textContent ?? "";
    expect(result).toContain("hello there");
    expect(result).toContain("en");
    expect(result).toContain("420 ms");
    test.mockRejectedValue(new Error("service said no"));
    file.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(card("second").querySelector('[role="alert"]')?.textContent).toContain("service said no");
    // An unavailable preset cannot be tested.
    expect(button(card("cloud"), "test")?.disabled).toBe(true);
    await unmount(section);
  });
});
