import { mount, unmount } from "svelte";
import { describe, expect, it, vi } from "vitest";
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

function agentMessage(body: string): ChatMessage {
  return {
    id: 2,
    conv_id: "line-1",
    sender: "sol",
    sender_type: "agent",
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

describe("agent message enhancements", () => {
  it("lazily renders labeled code and documented math markers", async () => {
    const body = String.raw`\(E=mc^2\)` + "\n\n```javascript\nconst answer = 42;\n```";
    const message = mount(Message, {
      target: document.body,
      props: { message: agentMessage(body) },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".katex")).not.toBeNull();
        expect(document.querySelector("code[data-code-highlighted='true']")).not.toBeNull();
      });
      expect(document.querySelector("code .hljs-keyword")?.textContent).toBe("const");
    } finally {
      await unmount(message);
    }
  });
});
