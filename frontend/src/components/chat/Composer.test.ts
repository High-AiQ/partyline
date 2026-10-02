import { mount, unmount } from "svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Composer from "./Composer.svelte";
import { layout } from "../../state/layout.svelte.js";
import { room } from "../../state/room.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { onRoomWireEvent } from "../../state/room-wire-events";
import type { Attachment } from "../../lib/contracts";
import { api } from "../../lib/api";

afterEach(() => {
  vi.restoreAllMocks();
  layout.narrow = false;
  room.leave({ clearRoute: false });
  room.notice = null;
  document.body.replaceChildren();
});

const conversation = {
  id: "composer-line",
  name: "Composer line",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 0,
};

const liveAttachment: Attachment = {
  id: "composer-worker",
  conv_id: "composer-line",
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

describe("composer narrow layout", () => {
  it("uses the short placeholder and a one-line minimum on narrow screens", async () => {
    layout.narrow = true;
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const input = document.querySelector<HTMLTextAreaElement>("#input");
      expect(input?.placeholder).toBe("say something…");
      expect(input?.classList.contains("min-h-7")).toBe(true);
    } finally {
      await unmount(component);
    }
  });

  it("keeps the addressing hint on desktop", async () => {
    layout.narrow = false;
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      expect(document.querySelector<HTMLTextAreaElement>("#input")?.placeholder).toBe(
        "say something… @name to ring an agent",
      );
    } finally {
      await unmount(component);
    }
  });
});

describe("composer process requirement", () => {
  it("keeps the draft and does not send on Enter while disabled", async () => {
    room.conversation = conversation;
    draft.openLine(conversation.id);
    draft.text = "still a draft";
    const say = vi.spyOn(room, "say");
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const input = document.querySelector<HTMLTextAreaElement>("#input");
      expect(document.querySelector<HTMLButtonElement>("#send")?.disabled).toBe(true);
      input?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      await tick();

      expect(say).not.toHaveBeenCalled();
      expect(draft.text).toBe("still a draft");
    } finally {
      await unmount(component);
    }
  });

  it("blocks text captions with files while keeping both the file and draft", async () => {
    room.conversation = conversation;
    draft.openLine(conversation.id);
    draft.text = "text caption must wait";
    const upload = vi.spyOn(api, "uploadFiles");
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const picker = document.querySelector<HTMLInputElement>('input[type="file"]');
      Object.defineProperty(picker, "files", {
        configurable: true,
        value: [new File(["file content"], "note.txt", { type: "text/plain" })],
      });
      picker?.dispatchEvent(new Event("change", { bubbles: true }));
      await tick();

      const send = document.querySelector<HTMLButtonElement>("#send");
      expect(send?.disabled).toBe(true);
      send?.click();
      await tick();

      expect(upload).not.toHaveBeenCalled();
      expect(draft.text).toBe("text caption must wait");
      expect(document.querySelector('[aria-label="files ready to attach"]')).not.toBeNull();
    } finally {
      await unmount(component);
    }
  });

  it("keeps a draft while disabled, then enables on a live attachment event", async () => {
    room.conversation = conversation;
    draft.openLine(conversation.id);
    draft.text = "held draft";
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const input = document.querySelector<HTMLTextAreaElement>("#input");
      const send = document.querySelector<HTMLButtonElement>("#send");
      expect(send?.disabled).toBe(true);
      expect(document.querySelector(".hint")?.textContent).toContain("attach a process to message this line");
      expect(input?.value).toBe("held draft");

      onRoomWireEvent(
        room,
        { type: "attachment", attachment: liveAttachment },
        { wasReady: true, claimRejected: false, rejectClaim: vi.fn() },
      );
      await tick();

      expect(send?.disabled).toBe(false);
      expect(input?.value).toBe("held draft");
    } finally {
      await unmount(component);
    }
  });

  it("shows a raced 409 and keeps the message draft", async () => {
    room.conversation = conversation;
    room.upsertAttachment(liveAttachment);
    draft.openLine(conversation.id);
    draft.text = "keep this after the process exits";
    vi.spyOn(room, "say").mockImplementation(() => {
      room.showNotice("attach a process to this line before sending", "error");
      return Promise.resolve(false);
    });
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      document.querySelector<HTMLButtonElement>("#send")?.click();
      await tick();

      expect(draft.text).toBe("keep this after the process exits");
      expect(room.notice?.message).toBe("attach a process to this line before sending");
    } finally {
      await unmount(component);
    }
  });
});
