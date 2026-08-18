import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import JackCard from "./JackCard.svelte";
import { presence } from "../../state/presence.svelte.js";
import type { Attachment } from "../../lib/contracts";

const attachment: Attachment = {
  id: "att-sol",
  conv_id: "conv-1",
  name: "sol",
  adapter: "codex",
  command: ["codex"],
  cwd: "/tmp/work",
  status: "running",
  last_seen: 1,
  created_at: 1,
  cli_session: null,
};

afterEach(() => {
  presence.clear();
});

describe("JackCard working receipt", () => {
  it("shows and clears only for the matching attachment", async () => {
    const other: Attachment = { ...attachment, id: "att-other", name: "other" };
    const card = mount(JackCard, {
      target: document.body,
      props: { attachment, resumable: false, overridesBundled: false, onmention: vi.fn() },
    });
    const second = mount(JackCard, {
      target: document.body,
      props: { attachment: other, resumable: false, overridesBundled: false, onmention: vi.fn() },
    });
    try {
      expect(document.querySelectorAll(".working")).toHaveLength(0);

      presence.apply({ type: "working", attachment_id: "att-other", working: true });
      await tick();
      expect(document.querySelectorAll(".working")).toHaveLength(1);
      expect(document.body.textContent).toContain("other");
      const badges = [...document.querySelectorAll(".working")];
      const jackText = (node: Element): string => node.closest(".jack")?.textContent ?? "";
      expect(badges.every((node) => jackText(node).includes("other"))).toBe(true);
      expect(badges.some((node) => jackText(node).includes("sol"))).toBe(false);

      presence.apply({ type: "working", attachment_id: attachment.id, working: true });
      await tick();
      expect(document.querySelectorAll(".working")).toHaveLength(2);

      presence.apply({ type: "working", attachment_id: attachment.id, working: false });
      await tick();
      expect(document.querySelectorAll(".working")).toHaveLength(1);
    } finally {
      await unmount(card);
      await unmount(second);
    }
  });
});
