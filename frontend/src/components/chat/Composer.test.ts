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
import { screenApi } from "../../lib/screen-api";

afterEach(() => {
  vi.restoreAllMocks();
  layout.narrow = false;
  room.leave({ clearRoute: false });
  room.screenShare = null;
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

describe("composer controls", () => {
  it("keeps hands-free, Show me and the screen-frame toggle as icons in the input row, with no controls row", async () => {
    room.conversation = conversation;
    room.screenShare = {
      share_id: "share",
      handle: "greg",
      device_name: "Desk",
      status: "active",
      region: { x: 0, y: 0, width: 100, height: 100 },
    };
    vi.spyOn(screenApi, "devices").mockResolvedValue({
      devices: [{ id: "desk", name: "Desk", os: "linux", online: true, monitors: [] }],
    });
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      await tick();
      const box = document.querySelector(".box");
      expect(document.querySelector("[data-composer-controls]")).toBeNull();
      const handsFree = box?.querySelector<HTMLButtonElement>("button.hands-free");
      expect(handsFree?.getAttribute("aria-label")).toMatch(/^Hands-free: off — /);
      expect(handsFree?.getAttribute("aria-pressed")).toBe("false");
      expect(handsFree?.textContent.trim()).toBe("");
      const showMe = box?.querySelector('button[aria-haspopup="menu"]');
      expect(showMe?.getAttribute("aria-label")).toBe(
        "Screen: share screen + record voice (Show me), or share screen only",
      );
      expect(showMe?.textContent.trim()).toBe("");
      const frames = box?.querySelector<HTMLButtonElement>('button[aria-label="Attach screen frames"]');
      expect(frames?.getAttribute("aria-pressed")).toBe("true");
      expect(document.querySelector("#composer")?.lastElementChild?.classList.contains("hint")).toBe(true);
    } finally {
      await unmount(component);
    }
  });

  it("hides Show me and the screen-frame toggle when they do not apply", async () => {
    room.conversation = conversation;
    room.screenShare = null;
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const box = document.querySelector(".box");
      expect(box?.querySelector('button[aria-label="Attach screen frames"]')).toBeNull();
      expect(box?.querySelector('button[aria-haspopup="menu"]')).not.toBeNull();
      expect(box?.querySelector("button.hands-free")).not.toBeNull();
    } finally {
      await unmount(component);
    }
  });
});

describe("composer process requirement", () => {
  it("clears immediately and restores a failed send without losing newer text", async () => {
    room.conversation = conversation;
    room.attachments = [liveAttachment];
    draft.openLine(conversation.id);
    draft.text = "first message";
    let resolve!: (value: boolean) => void;
    vi.spyOn(room, "say").mockReturnValue(new Promise((done) => (resolve = done)));
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      document
        .querySelector<HTMLTextAreaElement>("#input")
        ?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      expect(draft.text).toBe("");
      draft.text = "new draft";
      resolve(false);
      await tick();
      expect(draft.text).toBe("first message\nnew draft");
    } finally {
      await unmount(component);
    }
  });

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

describe("screen and voice controls", () => {
  it("sends ordinary messages without attaching a walkthrough's private frames", async () => {
    room.conversation = conversation;
    room.attachments = [liveAttachment];
    room.screenShare = {
      share_id: "share",
      handle: "alice",
      device_name: "Desk",
      region: { x: 0, y: 0, width: 100, height: 100 },
      status: "active",
      walkthrough: true,
    };
    draft.openLine(conversation.id);
    draft.text = "hello";
    const say = vi.spyOn(room, "say").mockResolvedValue(true);
    const upload = vi.spyOn(api, "uploadFiles");
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      document.querySelector<HTMLButtonElement>("#send")?.click();
      await tick();
      expect(say).toHaveBeenCalledWith("hello");
      expect(upload).not.toHaveBeenCalled();
    } finally {
      await unmount(component);
    }
  });

  it("attaches screen frames to a send only while the toggle is on", async () => {
    room.conversation = conversation;
    room.attachments = [liveAttachment];
    room.screenShare = {
      share_id: "share",
      handle: "alice",
      device_name: "Desk",
      region: { x: 0, y: 0, width: 100, height: 100 },
      status: "active",
    };
    draft.openLine(conversation.id);
    draft.text = "look";
    const say = vi.spyOn(room, "say").mockResolvedValue(true);
    const upload = vi.spyOn(api, "uploadFiles").mockResolvedValue(undefined as never);
    vi.spyOn(room, "resync").mockResolvedValue(undefined);
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const toggle = document.querySelector<HTMLButtonElement>('button[aria-label="Attach screen frames"]');
      toggle?.click();
      await tick();
      document.querySelector<HTMLButtonElement>("#send")?.click();
      await tick();
      expect(say).toHaveBeenCalledWith("look");
      expect(upload).not.toHaveBeenCalled();
      draft.text = "again";
      toggle?.click();
      await tick();
      document.querySelector<HTMLButtonElement>("#send")?.click();
      await tick();
      expect(upload).toHaveBeenCalledWith(
        conversation.id,
        expect.objectContaining({ body: "again", includeScreen: true }),
      );
    } finally {
      await unmount(component);
    }
  });

  it("keeps the microphone and the enabled screen attachment toggle together", async () => {
    room.conversation = conversation;
    room.screenShare = {
      share_id: "share",
      handle: "alice",
      device_name: "Desk",
      region: { x: -100, y: 0, width: 100, height: 100 },
      status: "active",
    };
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      expect(document.querySelector('[aria-label="record voice message"]')).not.toBeNull();
      const toggle = document.querySelector<HTMLButtonElement>('button[aria-label="Attach screen frames"]');
      expect(toggle?.getAttribute("aria-pressed")).toBe("true");
      toggle?.click();
      await tick();
      expect(toggle?.getAttribute("aria-pressed")).toBe("false");
      expect(toggle?.getAttribute("aria-label")).toBe("Attach screen frames");
    } finally {
      await unmount(component);
    }
  });
});

describe("composer length cap and counter", () => {
  const withLiveLine = (text: string) => {
    room.conversation = conversation;
    room.attachments = [liveAttachment];
    draft.openLine(conversation.id);
    draft.text = text;
  };

  it("caps the textarea at ten thousand characters", async () => {
    withLiveLine("");
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      expect(document.querySelector<HTMLTextAreaElement>("#input")?.maxLength).toBe(10_000);
    } finally {
      await unmount(component);
    }
  });

  it("shows no counter for a short draft, then a faint one, a warning, and a limit state", async () => {
    withLiveLine("short");
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      expect(document.querySelector(".hint .count")?.textContent).toBe("");
      for (const [length, text, tone] of [
        [1_234, "1,234 / 10,000", null],
        [9_500, "9,500 / 10,000", "text-gold"],
        [10_000, "10,000 / 10,000", "text-red"],
      ] as const) {
        draft.text = "x".repeat(length);
        await tick();
        const count = document.querySelector(".hint .count");
        expect(count?.textContent).toBe(text);
        expect(count?.classList.contains("text-gold")).toBe(tone === "text-gold");
        expect(count?.classList.contains("text-red")).toBe(tone === "text-red");
      }
      draft.text = "y".repeat(20_000);
      await tick();
      expect(document.querySelector(".hint .count")?.textContent).toBe("10,000 / 10,000");
    } finally {
      await unmount(component);
    }
  });

  it("keeps the counter on the narrow layout, where the keyboard advice is hidden", async () => {
    layout.narrow = true;
    withLiveLine("z".repeat(2_000));
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const hint = document.querySelector(".hint");
      expect(hint?.classList.contains("counting")).toBe(true);
      expect(hint?.querySelector(".count")?.textContent).toBe("2,000 / 10,000");
    } finally {
      await unmount(component);
    }
  });
});
