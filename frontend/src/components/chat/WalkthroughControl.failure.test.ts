import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import WalkthroughControl from "./WalkthroughControl.svelte";
import { api } from "../../lib/api";
import { screenApi } from "../../lib/screen-api";
import { voiceApi } from "../../lib/voice-api";
import { walkthroughApi } from "../../lib/walkthrough-api";
import { ApiError } from "../../lib/http";
import type { Attachment, Conversation } from "../../lib/contracts";
import type { RecorderSources } from "../../lib/voice-recorder";
import { draft } from "../../state/draft.svelte.js";
import { layout } from "../../state/layout.svelte.js";
import { room } from "../../state/room.svelte.js";
import { screenStatus } from "../../state/screen-status.svelte.js";
import { sendFailures } from "../../state/send-failures.svelte.js";
import { session } from "../../state/session.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { walkthrough } from "../../state/walkthrough.svelte.js";
import { wire } from "../../state/wire.svelte.js";

const NO_PROCESS = "attach a process to this line before sending";
const line: Conversation = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };
const other: Conversation = { ...line, id: "m", name: "M" };
const region = { x: 0, y: 0, width: 100, height: 100 };
const share = { share_id: "s", handle: "alice", device_name: "Desk", status: "active" as const, region };
const jack: Attachment = {
  id: "a",
  conv_id: "l",
  name: "sol",
  adapter: "codex",
  command: ["codex"],
  cwd: "/tmp",
  status: "running",
  last_seen: 0,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
};

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}
function button(text: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find(
    (item) => item.textContent.includes(text) || item.getAttribute("aria-label")?.startsWith(text),
  );
}
const bubble = (): string => document.querySelector("[data-send-failure]")?.textContent.trim() ?? "";

function sources(): RecorderSources {
  const stream = { getTracks: () => [{ stop: vi.fn(), label: "Headset" }] } as unknown as MediaStream;
  return {
    getUserMedia: () => Promise.resolve(stream),
    isTypeSupported: () => true,
    createRecorder: () => {
      const recorder = {
        state: "inactive",
        mimeType: "audio/webm",
        ondataavailable: null as ((e: { data: Blob }) => void) | null,
        onstop: null as (() => void) | null,
        onerror: null,
        start() {
          recorder.state = "recording";
        },
        stop() {
          recorder.state = "inactive";
          recorder.ondataavailable?.({ data: new Blob(["audio"]) });
          recorder.onstop?.();
        },
      };
      return recorder as unknown as MediaRecorder;
    },
  };
}

/** A take on line "l" whose first finish is refused with the no-process 409. */
async function refusedTake(inFlight?: { refuse?: (error: Error) => void }) {
  room.conversation = line;
  room.screenShare = null;
  draft.openLine(line.id);
  draft.clear();
  walkthrough.last = { line: "l", device: "d", region };
  screenStatus.devices = [{ id: "d", name: "Desk", os: "test", online: true, monitors: [] }];
  vi.spyOn(screenApi, "start").mockResolvedValue({ share_id: "s", status: "waiting" });
  vi.spyOn(screenApi, "current").mockResolvedValue({ share });
  vi.spyOn(walkthroughApi, "arm").mockResolvedValue({ ok: true });
  vi.spyOn(walkthroughApi, "stop").mockResolvedValue({ ok: true });
  const cancel = vi.spyOn(walkthroughApi, "cancel").mockResolvedValue({ ok: true });
  voicePresets.listing = {
    default: "fake",
    presets: [{ name: "fake", kind: "fake", available: true }],
  };
  vi.spyOn(voiceApi, "transcribe").mockResolvedValue({ text: "", duration: 1, language: "en", segments: [] });
  const finish = vi.spyOn(walkthroughApi, "finish");
  if (inFlight) finish.mockReturnValue(new Promise((_, reject) => (inFlight.refuse = reject)));
  else finish.mockRejectedValueOnce(new ApiError(NO_PROCESS, 409)).mockResolvedValue({ message: { id: 1 } });
  const component = mount(WalkthroughControl, { target: document.body, props: { sources: sources() } });
  await settle();
  button("Screen:")?.click();
  await tick();
  button("Share screen + record voice")?.click();
  await settle();
  button("Stop and send")?.click();
  await settle();
  return { component, finish, cancel };
}

/** Move to another line the way the app does, without a network. */
async function switchTo(target: Conversation): Promise<void> {
  session.user = { id: 1, email: "greg@example.com", handle: "greg" };
  vi.spyOn(wire, "connect").mockReturnValue(undefined);
  vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
  vi.spyOn(api, "conversation").mockResolvedValue({
    conversation: target,
    messages: [],
    has_more_messages: false,
    attachments: [],
    working: [],
    presence: null,
  });
  await room.open(target);
  await settle();
}

afterEach(() => {
  layout.narrow = false;
  voicePresets.reset();
  vi.restoreAllMocks();
  room.leave({ clearRoute: false });
  for (const id of ["l", "m"]) sendFailures.discard(id);
  walkthrough.last = null;
  session.clearSession();
  document.body.replaceChildren();
});

describe("a walkthrough the server refused for lack of a process", () => {
  it("shows the refusal with a way to dismiss it, keeping the take for retry", async () => {
    const { component } = await refusedTake();
    expect(bubble()).toContain(NO_PROCESS);
    button("dismiss")?.click();
    await settle();
    expect(bubble()).not.toContain(NO_PROCESS);
    expect(bubble()).toContain("walkthrough not sent");
    expect(button("retry")).toBeDefined();
    await unmount(component);
  });

  it("clears the refusal when a process attaches, without polling", async () => {
    const { component } = await refusedTake();
    expect(bubble()).toContain(NO_PROCESS);
    room.upsertAttachment({ ...jack, status: "detached" });
    await settle();
    expect(bubble()).toContain(NO_PROCESS);
    room.upsertAttachment(jack);
    await settle();
    expect(bubble()).not.toContain(NO_PROCESS);
    expect(button("retry")).toBeDefined();
    await unmount(component);
  });

  it("clears when a later send on the line succeeds", async () => {
    const { component } = await refusedTake();
    expect(bubble()).toContain(NO_PROCESS);
    sendFailures.sent("l");
    await settle();
    expect(bubble()).not.toContain(NO_PROCESS);
    await unmount(component);
  });

  it("retries with the audio it kept and then forgets the take", async () => {
    const { component, finish } = await refusedTake();
    const firstAudio = vi.mocked(voiceApi.transcribe).mock.calls[0]?.[1];
    button("retry")?.click();
    await settle();
    expect(finish).toHaveBeenCalledTimes(2);
    expect(vi.mocked(voiceApi.transcribe).mock.calls[1]?.[1]).toBe(firstAudio);
    expect(sendFailures.get("l")).toBeUndefined();
    expect(document.querySelector("[data-send-failure]")).toBeNull();
    await unmount(component);
  });

  it("gives the strip back to idle once the take is held, so the bubble is the only state", async () => {
    const { component } = await refusedTake();
    expect(document.querySelector('[aria-label="Walkthrough"]')).toBeNull();
    expect(button("Screen:")).toBeDefined();
    await unmount(component);
  });

  it("holds a refusal under the line it was sent from when you switch mid-send", async () => {
    const pending: { refuse?: (error: Error) => void } = {};
    const { component, finish, cancel } = await refusedTake(pending);
    expect(finish).toHaveBeenCalledOnce();
    cancel.mockClear();

    await switchTo(other);
    pending.refuse?.(new ApiError(NO_PROCESS, 409));
    await settle();

    expect(cancel).not.toHaveBeenCalled();
    expect(sendFailures.get("m")).toBeUndefined();
    expect(sendFailures.get("l")?.take?.share).toBe("s");
    expect(document.querySelector("[data-send-failure]")).toBeNull();
    await switchTo(line);
    expect(bubble()).toContain("walkthrough not sent");
    await unmount(component);
  });

  it("discard drops the take and releases its share", async () => {
    const { component, cancel } = await refusedTake();
    button("discard")?.click();
    await settle();
    expect(cancel).toHaveBeenCalledWith("l", "s");
    expect(sendFailures.get("l")).toBeUndefined();
    expect(document.querySelector("[data-send-failure]")).toBeNull();
    await unmount(component);
  });

  it("stays on its own line across switches and does not release the take", async () => {
    const { component, finish, cancel } = await refusedTake();
    await switchTo(other);
    expect(document.querySelector("[data-send-failure]")).toBeNull();
    expect(cancel).not.toHaveBeenCalled();

    await switchTo(line);
    // The refusal text does not come back; the held take does.
    expect(bubble()).not.toContain(NO_PROCESS);
    expect(bubble()).toContain("walkthrough not sent");
    button("retry")?.click();
    await settle();
    expect(finish).toHaveBeenCalledTimes(2);
    expect(document.querySelector("[data-send-failure]")).toBeNull();
    await unmount(component);
  });
});
