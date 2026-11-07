import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it } from "vitest";
import HandsFreeSettings from "./HandsFreeSettings.svelte";
import { handsFree, HandsFreePreferences } from "../../../state/hands-free.svelte.js";
afterEach(() => {
  handsFree.update({ enabled: false, pauseMs: 1400, hiddenMs: 60000 });
  localStorage.clear();
  document.body.replaceChildren();
});
it("persists device-local speech pause and hidden-tab timeout", async () => {
  const component = mount(HandsFreeSettings, { target: document.body });
  await tick();
  const pause = document.querySelector<HTMLSelectElement>("#voiceSpeechPause");
  const hidden = document.querySelector<HTMLSelectElement>("#voiceHiddenTimeout");
  if (!pause || !hidden) throw new Error("missing settings");
  pause.value = "1500";
  pause.dispatchEvent(new Event("change", { bubbles: true }));
  hidden.value = "300000";
  hidden.dispatchEvent(new Event("change", { bubbles: true }));
  await tick();
  expect(new HandsFreePreferences().value).toEqual({ enabled: false, pauseMs: 1500, hiddenMs: 300000 });
  await unmount(component);
});
it("rejects invalid saved timing values", () => {
  localStorage.setItem("partyline.voice.hands-free", JSON.stringify({ enabled: true, pauseMs: -1 }));
  expect(new HandsFreePreferences().value.pauseMs).toBe(1400);
});
