import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import VoicePresetForm from "./VoicePresetForm.svelte";
import { emptyDraft } from "../../../lib/asr-preset-form";
import type { AsrDraft } from "../../../lib/asr-preset-form";

const initial: AsrDraft = {
  ...emptyDraft("openai-compatible"),
  name: "cloud",
  baseUrl: "https://api.openai.com",
  model: "whisper-1",
  apiKeyEnv: "OPENAI_API_KEY",
  responseFormat: "verbose_json",
  language: "de",
  timeout: "60",
  prompt: "Partyline",
};

afterEach(() => {
  document.body.replaceChildren();
});

describe("whisper-1 switch", () => {
  it("saves once with gpt-transcribe and json, leaving the other fields alone", async () => {
    const onsave = vi.fn();
    const form = mount(VoicePresetForm, {
      target: document.body,
      props: { initial, editing: true, onsave, oncancel: vi.fn() },
    });
    const switchButton = [...document.querySelectorAll("button")].find(
      (b) => b.textContent.trim() === "Switch to gpt-transcribe and save",
    );
    switchButton?.click();
    flushSync();
    expect(onsave).toHaveBeenCalledOnce();
    expect(onsave).toHaveBeenCalledWith({ ...initial, model: "gpt-transcribe", responseFormat: "json" });
    await unmount(form);
  });
});
