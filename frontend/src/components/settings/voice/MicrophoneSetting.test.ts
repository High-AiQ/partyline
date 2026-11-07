import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MicrophoneSetting from "./MicrophoneSetting.svelte";
import { FALLBACK_NOTICE, readSavedMic } from "../../../lib/mic-device";
import { FakeAudioContext, fakeMicStream, gone } from "../../../lib/mic-fakes";
import { SILENCE_MS } from "../../../lib/mic-meter";

function info(deviceId: string, label: string): MediaDeviceInfo {
  return { kind: "audioinput", deviceId, label } as MediaDeviceInfo;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}

const button = (text: string) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === text);
const select = () => document.querySelector<HTMLSelectElement>("#voiceMicDevice");

let devices: MediaDeviceInfo[];
let getUserMedia: ReturnType<typeof vi.fn<(c: MediaStreamConstraints) => Promise<MediaStream>>>;
let stop: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  FakeAudioContext.made = [];
  vi.stubGlobal("AudioContext", FakeAudioContext);
  devices = [info("a", "Built-in"), info("b", "Headset (Jabra)")];
  const mic = fakeMicStream("Headset (Jabra)");
  stop = mic.stop;
  getUserMedia = vi.fn(() => Promise.resolve(mic.stream));
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      enumerateDevices: () => Promise.resolve(devices),
      getUserMedia,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
    configurable: true,
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.body.replaceChildren();
});

describe("Microphone setting", () => {
  it("lists the input devices and remembers the pick per browser", async () => {
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    expect([...(select()?.options ?? [])].map((o) => o.textContent.trim())).toEqual([
      "system default",
      "Built-in",
      "Headset (Jabra)",
    ]);
    const picker = select();
    if (!picker) throw new Error("no picker");
    picker.value = "b";
    picker.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(readSavedMic()).toBe("b");
    picker.value = "";
    picker.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(readSavedMic()).toBeNull();
    void unmount(comp);
  });

  it("starts from the saved choice, and says when that device is not connected", async () => {
    localStorage.setItem("partyline.voice.mic", "unplugged");
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    expect(select()?.value).toBe("unplugged");
    expect(document.body.textContent).toContain("saved microphone (not connected)");
    void unmount(comp);
  });

  it("offers to allow the mic when the names are hidden, then lists them", async () => {
    devices = [info("a", ""), info("b", "")];
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    expect(button("Allow mic to list devices")).toBeDefined();
    expect([...(select()?.options ?? [])].map((o) => o.textContent.trim())).toContain("Microphone 1");
    devices = [info("a", "Built-in"), info("b", "Headset (Jabra)")];
    button("Allow mic to list devices")?.click();
    await settle();
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stop).toHaveBeenCalled();
    expect(button("Allow mic to list devices")).toBeUndefined();
    expect(document.body.textContent).toContain("Built-in");
    void unmount(comp);
  });

  it("reports a refused permission", async () => {
    devices = [info("a", "")];
    getUserMedia.mockRejectedValueOnce(gone("NotAllowedError"));
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    button("Allow mic to list devices")?.click();
    await settle();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("permission was denied");
    void unmount(comp);
  });

  it("Test opens the chosen device and shows the meter, the mic name and the silence hint", async () => {
    localStorage.setItem("partyline.voice.mic", "b");
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    button("Test")?.click();
    await settle();
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "b" } } });
    FakeAudioContext.last().analyser.amplitude = 0.05;
    vi.advanceTimersByTime(100);
    await tick();
    expect(document.querySelector('[role="meter"]')?.getAttribute("aria-valuenow")).toBe("30");
    expect(document.body.textContent).toContain("Mic: Headset (Jabra)");
    expect(document.querySelector('[role="alert"]')).toBeNull();
    FakeAudioContext.last().analyser.amplitude = 0;
    vi.advanceTimersByTime(SILENCE_MS);
    await tick();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("no input detected");
    void unmount(comp);
  });

  it("Test falls back to the default mic with a notice when the saved one is gone", async () => {
    localStorage.setItem("partyline.voice.mic", "b");
    getUserMedia.mockRejectedValueOnce(gone("OverconstrainedError"));
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    button("Test")?.click();
    await settle();
    expect(getUserMedia).toHaveBeenLastCalledWith({ audio: true });
    expect(document.body.textContent).toContain(FALLBACK_NOTICE);
    expect(document.querySelector('[role="meter"]')).not.toBeNull();
    void unmount(comp);
  });

  it("Stop test, and unmounting, free the mic and the audio context", async () => {
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    button("Test")?.click();
    await settle();
    const first = FakeAudioContext.last();
    button("Stop test")?.click();
    await settle();
    expect(first.closed).toBe(true);
    expect(stop).toHaveBeenCalled();
    expect(document.querySelector('[role="meter"]')).toBeNull();

    stop.mockClear();
    button("Test")?.click();
    await settle();
    const second = FakeAudioContext.last();
    expect(second).not.toBe(first);
    void unmount(comp);
    expect(second.closed).toBe(true);
    expect(stop).toHaveBeenCalled();
  });

  it("ends a forgotten test by itself after 30 s", async () => {
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    button("Test")?.click();
    await settle();
    const context = FakeAudioContext.last();
    vi.advanceTimersByTime(30_000);
    await tick();
    expect(context.closed).toBe(true);
    expect(button("Test")).toBeDefined();
    void unmount(comp);
  });

  it("restarts the test on the newly chosen device", async () => {
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    button("Test")?.click();
    await settle();
    const picker = select();
    if (!picker) throw new Error("no picker");
    picker.value = "a";
    picker.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(getUserMedia).toHaveBeenLastCalledWith({ audio: { deviceId: { exact: "a" } } });
    expect(FakeAudioContext.made).toHaveLength(2);
    expect(FakeAudioContext.made[0]?.closed).toBe(true);
    void unmount(comp);
  });

  it("explains itself when the browser has no media devices", async () => {
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
    const comp = mount(MicrophoneSetting, { target: document.body });
    await settle();
    expect(document.body.textContent).toContain("cannot list microphones");
    void unmount(comp);
  });
});
