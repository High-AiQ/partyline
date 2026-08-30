import { mount, unmount } from "svelte";
import { describe, expect, it } from "vitest";
import Message from "./Message.svelte";
import type { ChatMessage } from "../../lib/contracts";

function systemMessage(body: string): ChatMessage {
  return {
    id: 1,
    conv_id: "line-1",
    sender: "system",
    sender_type: "system",
    body,
    created_at: 0,
    files: [],
  };
}

describe("system message", () => {
  it("preserves newlines and repeated spaces in operational notices", async () => {
    const message = mount(Message, {
      target: document.body,
      props: { message: systemMessage("first line\nsecond  line") },
    });
    try {
      expect(document.querySelector(".body")?.classList.contains("whitespace-pre-wrap")).toBe(true);
    } finally {
      await unmount(message);
    }
  });
});
