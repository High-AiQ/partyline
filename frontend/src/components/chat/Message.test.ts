import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
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

function setClipboard(clipboard: unknown): void {
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
}

function copyButton(): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>("button.copy");
  if (!button) throw new Error("copy button not rendered");
  return button;
}

afterEach(() => {
  setClipboard(undefined);
  document.body.replaceChildren();
});

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

describe("cross-line message", () => {
  it("tags a relayed message with the line it was said on and marks it direct", async () => {
    const relayed: ChatMessage = {
      ...agentMessage("@lead page one is done"),
      source_conv_id: "line-2",
      source_conv_name: "Child",
      audience_attachment_id: "lead",
    };
    const message = mount(Message, { target: document.body, props: { message: relayed } });
    try {
      expect(document.querySelector(".via")?.textContent).toBe("via «Child»");
      expect(document.querySelector(".direct")?.textContent).toContain("direct");
    } finally {
      await unmount(message);
    }
  });

  it("leaves a message said on this line untagged", async () => {
    const local: ChatMessage = { ...agentMessage("hello"), source_conv_id: "line-1" };
    const message = mount(Message, { target: document.body, props: { message: local } });
    try {
      expect(document.querySelector(".via")).toBeNull();
      expect(document.querySelector(".direct")).toBeNull();
    } finally {
      await unmount(message);
    }
  });
});

describe("copy control", () => {
  it("is absent on system messages", async () => {
    const message = mount(Message, {
      target: document.body,
      props: { message: systemMessage("operational notice") },
    });
    try {
      expect(document.querySelector("button.copy")).toBeNull();
    } finally {
      await unmount(message);
    }
  });

  it("copies the wire markdown, not the rendered html", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const body = "**bold** `code`\n\n\\(E=mc^2\\)";
    const message = mount(Message, { target: document.body, props: { message: agentMessage(body) } });
    try {
      copyButton().click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(body);
      expect(document.querySelector(".body")?.innerHTML).toContain("<strong>");
    } finally {
      await unmount(message);
    }
  });

  it("shows the copied confirmation for about 1.5s, then reverts", async () => {
    vi.useFakeTimers();
    try {
      setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
      const message = mount(Message, {
        target: document.body,
        props: { message: agentMessage("hello") },
      });
      try {
        const button = copyButton();
        button.click();
        await vi.advanceTimersByTimeAsync(0);
        button.dispatchEvent(new MouseEvent("mouseenter"));
        expect(document.querySelector(".app-tooltip")?.textContent).toBe("Copied");
        await vi.advanceTimersByTimeAsync(1500);
        button.dispatchEvent(new MouseEvent("mouseleave"));
        button.dispatchEvent(new MouseEvent("mouseenter"));
        expect(document.querySelector(".app-tooltip")?.textContent).toBe("copy message");
      } finally {
        await unmount(message);
      }
    } finally {
      vi.useRealTimers();
    }
  });
});
