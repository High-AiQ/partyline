import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Message from "./Message.svelte";
import type { ChatMessage } from "../../lib/contracts";
import { renderMessage } from "../../lib/markdown";
import { room } from "../../state/room.svelte.js";
import { session } from "../../state/session.svelte.js";

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

function humanMessage(body: string): ChatMessage {
  return {
    ...agentMessage(body),
    id: 3,
    sender: "greg",
    sender_type: "human",
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

function copyTip(): HTMLElement | null {
  return document.getElementById(copyButton().getAttribute("aria-describedby") ?? "");
}

function copyMenu(): HTMLElement {
  const menu = document.querySelector<HTMLElement>("[role=menu]");
  if (!menu) throw new Error("copy menu not rendered");
  return menu;
}

async function openCopyMenu(): Promise<void> {
  copyButton().click();
  await vi.waitFor(() => {
    expect(document.querySelector("[role=menu]")).not.toBeNull();
  });
}

function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("clipboard blob was not text"));
    });
    reader.addEventListener("error", () => {
      reject(new Error("could not read clipboard blob"));
    });
    reader.readAsText(blob);
  });
}

afterEach(() => {
  setClipboard(undefined);
  session.user = null;
  session.authReady = false;
  room.pins.clear();
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

  it("has no copy, reaction, or chip controls", async () => {
    const message = mount(Message, {
      target: document.body,
      props: { message: systemMessage("☺ greg reacted ✅ to your notice") },
    });
    try {
      expect(document.querySelector("button.copy")).toBeNull();
      expect(document.querySelector("button.reaction-add")).toBeNull();
      expect(document.querySelector(".reaction-chips")).toBeNull();
      expect(document.querySelector("button.pin")).toBeNull();
    } finally {
      await unmount(message);
    }
  });

  it("offers pinning on normal messages but never on system notices", async () => {
    session.user = { id: 1, email: "greg@example.com", handle: "greg" };
    session.authReady = true;
    const notice = mount(Message, { target: document.body, props: { message: systemMessage("connected") } });
    try {
      expect(document.querySelector("button.pin")).toBeNull();
    } finally {
      await unmount(notice);
    }

    const ordinary = mount(Message, { target: document.body, props: { message: agentMessage("ready") } });
    try {
      const control = document.querySelector<HTMLButtonElement>("button.pin");
      expect(control?.getAttribute("aria-label")).toBe("pin message");
      expect(control?.querySelector("svg")?.getAttribute("fill")).toBe("none");
    } finally {
      await unmount(ordinary);
    }
  });
});

describe("reaction affordance", () => {
  it("puts a keyboard-reachable smiley beside the header copy control", async () => {
    const message = mount(Message, {
      target: document.body,
      props: { message: agentMessage("ready") },
    });
    try {
      const header = document.querySelector(".head");
      expect(header?.querySelector("button.reaction-add")).not.toBeNull();
      expect(header?.querySelector("button.copy")).not.toBeNull();
      expect(document.querySelector(".reaction-chips")).toBeNull();
      expect(document.querySelector(".reaction-row")).toBeNull();
    } finally {
      await unmount(message);
    }
  });

  it("shows the same header affordance for a human and chips below reactions", async () => {
    const message = mount(Message, {
      target: document.body,
      props: {
        message: {
          ...humanMessage("looks good"),
          reactions: [{ emoji: "✅", reactors: ["greg", "sol"], mine: true }],
        },
      },
    });
    try {
      expect(document.querySelector(".head button.reaction-add")).not.toBeNull();
      const chips = document.querySelector(".reaction-chips");
      expect(chips).not.toBeNull();
      expect(chips?.previousElementSibling?.classList.contains("body")).toBe(true);
      expect(chips?.textContent).toContain("2");
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

  it("opens a keyboard menu and copies the raw markdown item", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const body = "**bold** `code`\n\n\\(E=mc^2\\)";
    const message = mount(Message, { target: document.body, props: { message: agentMessage(body) } });
    try {
      await openCopyMenu();
      const items = copyMenu().querySelectorAll<HTMLElement>("[role=menuitem]");
      expect(items).toHaveLength(2);
      const markdownItem = items.item(0);
      const formattedItem = items.item(1);
      expect(markdownItem.textContent.trim()).toBe("copy markdown");
      expect(formattedItem.textContent.trim()).toBe("copy formatted text");
      items[0]?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
      expect(document.activeElement).toBe(items[1]);
      items[0]?.click();
      await vi.waitFor(() => {
        expect(writeText).toHaveBeenCalledTimes(1);
      });
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(body);
      expect(document.querySelector(".body")?.innerHTML).toContain("<strong>");
      expect(document.querySelector("[role=menu]")).toBeNull();
      expect(document.activeElement).toBe(copyButton());
    } finally {
      await unmount(message);
    }
  });

  it("closes on Escape, outside click, and focus leaving", async () => {
    const message = mount(Message, { target: document.body, props: { message: agentMessage("hello") } });
    try {
      await openCopyMenu();
      copyMenu().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await vi.waitFor(() => {
        expect(document.querySelector("[role=menu]")).toBeNull();
      });
      expect(document.activeElement).toBe(copyButton());
      await openCopyMenu();
      document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
      await vi.waitFor(() => {
        expect(document.querySelector("[role=menu]")).toBeNull();
      });
      await openCopyMenu();
      const outside = document.createElement("button");
      document.body.append(outside);
      outside.focus();
      await vi.waitFor(() => {
        expect(document.querySelector("[role=menu]")).toBeNull();
      });
    } finally {
      await unmount(message);
    }
  });

  it("copies exact contents from plain and language-tagged human code blocks", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const first = "<tag> &\tvalue";
    const second = "line one\nline two\n";
    const body = "before\n\n```\n" + first + "\n```\n\n```typescript\n" + second + "\n```";
    const message = mount(Message, { target: document.body, props: { message: humanMessage(body) } });
    try {
      const buttons = await vi.waitFor(() => {
        const found = [...document.querySelectorAll<HTMLButtonElement>("button.code-copy")];
        expect(found).toHaveLength(2);
        return found;
      });
      buttons[0]?.click();
      await vi.waitFor(() => {
        expect(writeText).toHaveBeenCalledTimes(1);
      });
      expect(writeText).toHaveBeenLastCalledWith(first);
      await vi.waitFor(() => {
        expect(buttons[0]?.getAttribute("aria-label")).toBe("copied");
      });
      expect(document.querySelector(".code-copy-status")?.getAttribute("aria-live")).toBe("polite");
      buttons[1]?.click();
      await vi.waitFor(() => {
        expect(writeText).toHaveBeenCalledTimes(2);
      });
      expect(writeText).toHaveBeenLastCalledWith(second);
    } finally {
      await unmount(message);
    }
  });

  it("copies Marked's exact code text for truncated, indented, and blank-line-ending blocks", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const cases = [
      { body: "```\na\nb", expected: "a\nb" },
      { body: "    x = 1\n    y = 2", expected: "x = 1\ny = 2", agent: true },
      { body: "  ```\n  a\n    b\n  ```", expected: "a\n  b" },
      { body: "```\na\nb\n```", expected: "a\nb" },
      { body: "```\na\nb\n\n```", expected: "a\nb\n" },
    ];

    let copyCount = 0;
    for (const { body, expected, agent } of cases) {
      const content = agent ? agentMessage(body) : humanMessage(body);
      const message = mount(Message, { target: document.body, props: { message: content } });
      try {
        const button = await vi.waitFor(() => {
          const found = document.querySelector<HTMLButtonElement>("button.code-copy");
          expect(found).not.toBeNull();
          if (!found) throw new Error("code copy button missing");
          return found;
        });
        button.click();
        copyCount += 1;
        await vi.waitFor(() => {
          expect(writeText).toHaveBeenCalledTimes(copyCount);
        });
        expect(writeText).toHaveBeenLastCalledWith(expected);
      } finally {
        await unmount(message);
      }
    }
  });

  it("keeps human headings, lists, and tables in the original inline-only layout", async () => {
    const body = "paragraph first line\nparagraph second line\n# x\n1. y\n| a | b |\n|---|---|\n| c | d |";
    const message = mount(Message, { target: document.body, props: { message: humanMessage(body) } });
    try {
      const rendered = document.querySelector<HTMLElement>(".body");
      expect(rendered).not.toBeNull();
      expect(rendered?.innerHTML).toBe(renderMessage(body, false));
      expect(rendered?.classList.contains("whitespace-pre-wrap")).toBe(true);
      expect(rendered?.querySelector("h1, ol, ul, table")).toBeNull();
      expect(rendered?.textContent).toContain("paragraph first line\nparagraph second line\n# x\n1. y");
    } finally {
      await unmount(message);
    }
  });

  it("keeps indented human logs as pre-wrapped text instead of code blocks", async () => {
    const body = "hi\n\n    indented log line\n    second\n\nbye";
    const message = mount(Message, { target: document.body, props: { message: humanMessage(body) } });
    try {
      const rendered = document.querySelector<HTMLElement>(".body");
      expect(rendered?.innerHTML).toBe(renderMessage(body, false));
      expect(rendered?.classList.contains("whitespace-pre-wrap")).toBe(true);
      expect(rendered?.querySelector("pre, button.code-copy")).toBeNull();
      expect(rendered?.textContent).toContain("    indented log line\n    second");
    } finally {
      await unmount(message);
    }
  });

  it("adds a copyable highlighted fence to human inline text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const prose = "paragraph first line\nparagraph second line\n# x\n1. y\n| a | b |";
    const source = "const output = '<tag> & ok';";
    const body = `${prose}\n\n\`\`\`typescript\n${source}\n\`\`\``;
    const message = mount(Message, { target: document.body, props: { message: humanMessage(body) } });
    try {
      const block = await vi.waitFor(() => {
        const found = document.querySelector<HTMLElement>(".body pre code[data-code-language='typescript']");
        expect(found).not.toBeNull();
        return found;
      });
      expect(document.querySelector(".body h1, .body ol, .body ul, .body table")).toBeNull();
      const copy = await vi.waitFor(() => {
        const found = document.querySelector<HTMLButtonElement>(".body button.code-copy");
        expect(found).not.toBeNull();
        return found;
      });
      expect(document.querySelectorAll(".body button.code-copy")).toHaveLength(1);
      copy?.click();
      await vi.waitFor(() => {
        expect(writeText).toHaveBeenCalledWith(source);
      });
      expect(block?.textContent).toContain("<tag> & ok");
    } finally {
      await unmount(message);
    }
  });

  it("adds a copy button to an unclosed human fence", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const source = "print('still open')";
    const message = mount(Message, {
      target: document.body,
      props: { message: humanMessage(`before fence\n\n\`\`\`python\n${source}`) },
    });
    try {
      const button = await vi.waitFor(() => {
        const found = document.querySelector<HTMLButtonElement>(".body button.code-copy");
        expect(found).not.toBeNull();
        return found;
      });
      expect(document.querySelector(".body code[data-code-language='python']")).not.toBeNull();
      button?.click();
      await vi.waitFor(() => {
        expect(writeText).toHaveBeenCalledWith(source);
      });
    } finally {
      await unmount(message);
    }
  });

  it("resets the code-block copied state after about 1.5 seconds", async () => {
    setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
    const message = mount(Message, {
      target: document.body,
      props: { message: humanMessage("```\nhello\n```") },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("button.code-copy")).not.toBeNull();
      });
      vi.useFakeTimers();
      const button = document.querySelector<HTMLButtonElement>("button.code-copy");
      if (!button) throw new Error("code copy button missing");
      button.click();
      await vi.advanceTimersByTimeAsync(0);
      expect(button.getAttribute("aria-label")).toBe("copied");
      expect(document.querySelector(".code-copy-status")?.textContent).toBe("copied");
      await vi.advanceTimersByTimeAsync(1500);
      expect(button.getAttribute("aria-label")).toBe("copy code block");
      expect(document.querySelector(".code-copy-status")?.textContent).toBe("");
    } finally {
      vi.useRealTimers();
      await unmount(message);
    }
  });

  it("copies formatted HTML and plain text without copy controls", async () => {
    class TestClipboardItem {
      constructor(readonly values: Record<string, Blob>) {}
    }
    vi.stubGlobal("ClipboardItem", TestClipboardItem);
    let copiedItem: TestClipboardItem | undefined;
    const write = vi.fn((items: ClipboardItem[]): Promise<void> => {
      copiedItem = items[0] as unknown as TestClipboardItem;
      return Promise.resolve();
    });
    setClipboard({ write });
    const body = "**bold**\n\n```js\nconst x = 1;\n```";
    const message = mount(Message, { target: document.body, props: { message: humanMessage(body) } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".code-copy")).not.toBeNull();
      });
      await openCopyMenu();
      copyMenu().querySelectorAll<HTMLElement>("[role=menuitem]")[1]?.click();
      await vi.waitFor(() => {
        expect(write).toHaveBeenCalledTimes(1);
      });
      const item = copiedItem;
      if (!item) throw new Error("clipboard item missing");
      const htmlBlob = item.values["text/html"];
      const textBlob = item.values["text/plain"];
      if (!htmlBlob || !textBlob) throw new Error("clipboard formats missing");
      const html = await blobText(htmlBlob);
      const text = await blobText(textBlob);
      expect(html).toContain("<strong>bold</strong>");
      expect(html).toContain('class="hljs-keyword"');
      expect(html).not.toContain("code-copy");
      expect(html).not.toContain("copy code block");
      expect(text).toContain("bold");
      expect(text).toContain("const x = 1;");
    } finally {
      await unmount(message);
      vi.unstubAllGlobals();
    }
  });

  it("reports when copying is unavailable", async () => {
    setClipboard(undefined);
    Object.defineProperty(document, "execCommand", { value: () => false, configurable: true });
    const message = mount(Message, { target: document.body, props: { message: agentMessage("hello") } });
    try {
      await openCopyMenu();
      copyMenu().querySelector<HTMLElement>("[role=menuitem]")?.click();
      await vi.waitFor(() => {
        expect(room.notice?.message).toContain("Could not copy");
      });
    } finally {
      await unmount(message);
      delete (document as { execCommand?: unknown }).execCommand;
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
        await Promise.resolve();
        copyMenu().querySelector<HTMLElement>("[role=menuitem]")?.click();
        await vi.advanceTimersByTimeAsync(0);
        button.dispatchEvent(new MouseEvent("mouseenter"));
        expect(copyTip()?.textContent).toBe("Copied");
        await vi.advanceTimersByTimeAsync(1500);
        button.dispatchEvent(new MouseEvent("mouseleave"));
        button.dispatchEvent(new MouseEvent("mouseenter"));
        expect(copyTip()?.textContent).toBe("copy message");
      } finally {
        await unmount(message);
      }
    } finally {
      vi.useRealTimers();
    }
  });
});
