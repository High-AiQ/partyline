import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Message from "./Message.svelte";
import type { ChatMessage, Conversation } from "../../lib/contracts";
import { room } from "../../state/room.svelte.js";
import { session } from "../../state/session.svelte.js";
import { reviewDecisionStatus } from "../../state/review-decision-status.svelte.js";
import { dialogs } from "../../state/dialogs.svelte.js";

const conversation: Conversation = {
  id: "conv-1",
  name: "storytime updates 13",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 1,
};

function clickButton(selector: string): void {
  const button = document.querySelector(selector);
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`missing ${selector}`);
  }
  button.click();
}

afterEach(() => {
  room.conversation = null;
  session.user = null;
  session.authReady = true;
  reviewDecisionStatus.entries = {};
  dialogs.closeAll();
  document.body.replaceChildren();
});

function humanMessage(body: string): ChatMessage {
  return {
    id: 3,
    conv_id: "line-1",
    sender: "greg",
    sender_type: "human",
    body,
    created_at: 0,
    files: [],
  };
}

describe("review affordance", () => {
  it("shows a review control only for signed-in humans on agent messages", async () => {
    room.conversation = conversation;
    session.authReady = true;
    session.user = { id: 1, email: "greg@example.com", handle: "greg" };
    const message = mount(Message, {
      target: document.body,
      props: { message: agentMessage("ship the producer path") },
    });
    try {
      expect(document.querySelector(".review-btn")).not.toBeNull();
    } finally {
      await unmount(message);
    }
  });

  it("hides review on system and human messages", async () => {
    room.conversation = conversation;
    session.authReady = true;
    session.user = { id: 1, email: "greg@example.com", handle: "greg" };
    const system = mount(Message, {
      target: document.body,
      props: { message: systemMessage("topic set") },
    });
    await unmount(system);
    mount(Message, {
      target: document.body,
      props: { message: humanMessage("looks good") },
    });
    expect(document.querySelector(".review-btn")).toBeNull();
  });

  it("opens the review dialog instead of posting immediately", async () => {
    room.conversation = conversation;
    session.authReady = true;
    session.user = { id: 1, email: "greg@example.com", handle: "greg" };
    const open = vi.spyOn(dialogs, "open");
    const message = mount(Message, {
      target: document.body,
      props: { message: agentMessage("ready for review") },
    });
    try {
      clickButton(".review-btn");
      expect(open).toHaveBeenCalledOnce();
    } finally {
      await unmount(message);
    }
  });
});

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
