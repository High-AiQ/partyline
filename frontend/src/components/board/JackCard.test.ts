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
    const card = mount(JackCard, {
      target: document.body,
      props: { attachment, resumable: false, overridesBundled: false, onmention: vi.fn() },
    });
    try {
      expect(document.querySelector(".working")).toBeNull();

      presence.apply({ type: "working", attachment_id: attachment.id, working: true });
      await tick();
      expect(document.querySelector(".working")?.textContent).toContain("working…");

      presence.apply({ type: "working", attachment_id: attachment.id, working: false });
      await tick();
      expect(document.querySelector(".working")).toBeNull();
    } finally {
      await unmount(card);
    }
  });
});
