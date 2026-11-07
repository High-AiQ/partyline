import { mount, tick, unmount } from "svelte";
import { describe, expect, it, vi } from "vitest";
import Message from "./Message.svelte";
import { dialogs } from "../../state/dialogs.svelte";
import type { ChatMessage, FileRef } from "../../lib/contracts";

function image(id: string, title: string): FileRef {
  return {
    id,
    title,
    kind: "image",
    filename: null,
    description: null,
    mime: "image/png",
    bytes: 10,
    width: 100,
    height: 100,
    thumb: null,
    slim: null,
    urls: { original: `/api/media/${id}/original`, thumb: `/api/media/${id}/thumb`, slim: null },
  };
}

function message(files: FileRef[]): ChatMessage {
  return {
    id: 1,
    conv_id: "line",
    sender: "greg",
    sender_type: "human",
    created_at: 1,
    files,
    body: 'Walkthrough · 0:31 · 2 frames\n[0:01] "Hello."\nContact sheet first: open it, then fetch only the frames you need\n[0:02] → frame 1\n📷 sheet\n📷 frame\n📷 frame',
  };
}

describe("walkthrough message", () => {
  it("shows only the sheet and opens all images in the viewer", async () => {
    const files = [
      image("sheet", "Walkthrough contact sheet"),
      image("one", "Walkthrough frame"),
      image("two", "Walkthrough frame"),
    ];
    const open = vi.spyOn(dialogs, "open").mockImplementation(() => () => undefined);
    const component = mount(Message, { target: document.body, props: { message: message(files) } });
    try {
      expect(document.querySelectorAll(".tile")).toHaveLength(1);
      expect(document.querySelector(".body")?.textContent).toContain('"Hello."');
      expect(document.querySelector(".body")?.textContent).not.toContain("→ frame");
      document.querySelector<HTMLButtonElement>(".tile")?.click();
      expect(open.mock.calls[0]?.[1]).toEqual({ images: files, initialIndex: 0 });
    } finally {
      await unmount(component);
      open.mockRestore();
    }
  });

  it("keeps ordinary image uploads visible", async () => {
    const files = [image("one", "photo"), image("two", "photo")];
    const component = mount(Message, { target: document.body, props: { message: message(files) } });
    try {
      await tick();
      expect(document.querySelectorAll(".tile")).toHaveLength(2);
    } finally {
      await unmount(component);
    }
  });
});
