import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import FreshJackDialog from "./FreshJackDialog.svelte";
import { attachmentLifecycleApi } from "../../lib/attachment-lifecycle-api";
import { room } from "../../state/room.svelte.js";
import type { Attachment } from "../../lib/contracts";

const stopped: Attachment = {
  id: "att-old",
  conv_id: "conv-1",
  name: "sol",
  adapter: "codex",
  command: ["codex"],
  cwd: "/tmp/work",
  status: "detached",
  last_seen: 20,
  created_at: 1,
  cli_session: "session-1",
  cwd_git: null,
};
const replacement: Attachment = { ...stopped, id: "att-new", status: "starting", cli_session: null };

const conversation = {
  id: "conv-1",
  name: "work room",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 0,
};

afterEach(() => {
  vi.restoreAllMocks();
  room.attachments = [];
  room.conversation = null;
});

function type(id: string, value: string): void {
  const input = document.getElementById(id);
  if (!(input instanceof HTMLInputElement)) throw new Error(`no input #${id}`);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

async function submit(): Promise<void> {
  const form = document.querySelector("form");
  if (!form) throw new Error("no form");
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await tick();
  await Promise.resolve();
  await tick();
}

function open() {
  const close = vi.fn();
  room.conversation = conversation;
  room.attachments = [stopped];
  const dialog = mount(FreshJackDialog, { target: document.body, props: { attachment: stopped, close } });
  return { dialog, close };
}

describe("FreshJackDialog", () => {
  it("sends a checkpoint alone and swaps the old card for the replacement", async () => {
    const fresh = vi.spyOn(attachmentLifecycleApi, "fresh").mockResolvedValue(replacement);
    const { dialog, close } = open();
    try {
      type("freshCheckpoint", " docs/agent-checkpoints/book/task.md ");
      await submit();
      expect(fresh).toHaveBeenCalledWith("att-old", { checkpoint: "docs/agent-checkpoints/book/task.md" });
      expect(room.attachments.map((attachment) => attachment.id)).toEqual(["att-new"]);
      expect(close).toHaveBeenCalledOnce();
    } finally {
      await unmount(dialog);
    }
  });

  it("sends the checkpoint with its replay boundary", async () => {
    const fresh = vi.spyOn(attachmentLifecycleApi, "fresh").mockResolvedValue(replacement);
    const { dialog } = open();
    try {
      type("freshCheckpoint", "ckpt.md");
      type("freshAfterMessage", "123");
      await submit();
      expect(fresh).toHaveBeenCalledWith("att-old", { checkpoint: "ckpt.md", after_message_id: 123 });
    } finally {
      await unmount(dialog);
    }
  });

  it("refuses a boundary without a checkpoint before any request is made", async () => {
    const fresh = vi.spyOn(attachmentLifecycleApi, "fresh").mockResolvedValue(replacement);
    const { dialog, close } = open();
    try {
      type("freshAfterMessage", "123");
      await submit();
      expect(fresh).not.toHaveBeenCalled();
      expect(close).not.toHaveBeenCalled();
      expect(document.querySelector(".line-status")?.textContent).toContain("needs a checkpoint");
      expect(room.attachments.map((attachment) => attachment.id)).toEqual(["att-old"]);
    } finally {
      await unmount(dialog);
    }
  });

  it("leaves the roster alone when the user has moved to another line meanwhile", async () => {
    vi.spyOn(attachmentLifecycleApi, "fresh").mockImplementation(() => {
      room.conversation = { ...conversation, id: "conv-2" };
      room.attachments = [];
      return Promise.resolve(replacement);
    });
    const { dialog, close } = open();
    try {
      await submit();
      expect(room.attachments).toEqual([]);
      expect(close).toHaveBeenCalledOnce();
    } finally {
      await unmount(dialog);
    }
  });

  it("keeps the old card when the server refuses, and shows its reason", async () => {
    const { ApiError } = await import("../../lib/api");
    vi.spyOn(attachmentLifecycleApi, "fresh").mockRejectedValue(new ApiError("'sol' is already live", 409));
    const { dialog, close } = open();
    try {
      await submit();
      expect(document.querySelector(".line-status")?.textContent).toContain("already live");
      expect(room.attachments.map((attachment) => attachment.id)).toEqual(["att-old"]);
      expect(close).not.toHaveBeenCalled();
    } finally {
      await unmount(dialog);
    }
  });
});
