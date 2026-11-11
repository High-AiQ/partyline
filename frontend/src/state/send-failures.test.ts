import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/http";
import * as roomSay from "../lib/room-say";
import type { Attachment, Conversation } from "../lib/contracts";
import { room } from "./room.svelte.js";
import { SendFailures, type HeldTake } from "./send-failures.svelte.js";
import { sendFailures } from "./send-failures.svelte.js";

const NO_PROCESS = new ApiError("attach a process to this line before sending", 409);
const take: HeldTake = { audio: new Blob(["a"]), share: "s", mark: false, elapsed: 5 };
const conversation: Conversation = {
  id: "l",
  name: "L",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 0,
};
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

afterEach(() => {
  vi.restoreAllMocks();
  sendFailures.discard("l");
  room.leave({ clearRoute: false });
});

describe("SendFailures", () => {
  it("is keyed by line", () => {
    const failures = new SendFailures();
    failures.fail("a", NO_PROCESS);
    expect(failures.get("a")?.message).toBe(NO_PROCESS.message);
    expect(failures.get("b")).toBeUndefined();
    expect(failures.get(null)).toBeUndefined();
  });

  it("dismissal removes a plain failure but keeps a held take without its message", () => {
    const failures = new SendFailures();
    failures.fail("a", NO_PROCESS);
    failures.dismiss("a");
    expect(failures.get("a")).toBeUndefined();
    failures.fail("a", NO_PROCESS, take);
    failures.dismiss("a");
    expect(failures.get("a")).toEqual({ message: "", noProcess: false, take });
  });

  it("an attachment ends only a no-process refusal", () => {
    const failures = new SendFailures();
    failures.fail("a", new Error("disk full"));
    failures.attached("a");
    expect(failures.get("a")?.message).toBe("disk full");
    failures.fail("a", NO_PROCESS);
    failures.attached("a");
    expect(failures.get("a")).toBeUndefined();
  });

  it("does not hold a take the server no longer has", () => {
    const failures = new SendFailures();
    failures.fail("a", new ApiError("walkthrough not found", 404), take);
    expect(failures.get("a")?.take).toBeNull();
  });

  it("discard hands back the take", () => {
    const failures = new SendFailures();
    failures.fail("a", NO_PROCESS, take);
    expect(failures.discard("a")).toBe(take);
    expect(failures.get("a")).toBeUndefined();
    expect(failures.discard("a")).toBeNull();
  });
});

describe("the room and failed sends", () => {
  it("clears a no-process refusal when a live process attaches on that line", () => {
    room.conversation = conversation;
    sendFailures.fail("l", NO_PROCESS);
    room.upsertAttachment({ ...jack, status: "detached" });
    expect(sendFailures.get("l")).toBeDefined();
    room.upsertAttachment(jack);
    expect(sendFailures.get("l")).toBeUndefined();
  });

  it("clears it when a later send succeeds", async () => {
    room.conversation = conversation;
    sendFailures.fail("l", NO_PROCESS);
    vi.spyOn(roomSay, "sayOnLine").mockResolvedValue({ ok: true });
    await room.say("hello");
    expect(sendFailures.get("l")).toBeUndefined();
  });

  it("keeps it when the send fails again", async () => {
    room.conversation = conversation;
    sendFailures.fail("l", NO_PROCESS);
    vi.spyOn(roomSay, "sayOnLine").mockResolvedValue({ ok: false, error: "nope" });
    await room.say("hello");
    expect(sendFailures.get("l")).toBeDefined();
  });

  it("drops the message when leaving the line but keeps a held take for it", () => {
    room.conversation = conversation;
    sendFailures.fail("l", NO_PROCESS);
    room.leave({ clearRoute: false });
    expect(sendFailures.get("l")).toBeUndefined();
    room.conversation = conversation;
    sendFailures.fail("l", NO_PROCESS, take);
    room.leave({ clearRoute: false });
    expect(sendFailures.get("l")?.message).toBe("");
    expect(sendFailures.get("l")?.take).toBe(take);
  });

  it("dismisses a notice on request", () => {
    room.showNotice("boom", "error");
    room.notice = null;
    expect(room.notice).toBeNull();
  });
});
