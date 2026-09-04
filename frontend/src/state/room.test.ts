import { afterEach, describe, expect, it, vi } from "vitest";
import { room } from "./room.svelte.js";
import { api } from "../lib/api";
import type { Attachment, Conversation, ConversationDetail } from "../lib/contracts";

const jack: Attachment = {
  id: "att-1",
  conv_id: "conv-1",
  name: "sol",
  adapter: "codex",
  command: ["codex"],
  cwd: "/tmp/work",
  status: "detached",
  last_seen: 0,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
};

const conversation: Conversation = {
  id: "conv-1",
  name: "work room",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 0,
};

afterEach(() => {
  vi.restoreAllMocks();
  room.leave({ clearRoute: false });
});

describe("room roster after a removal", () => {
  it("does not let a late attachment state event resurrect a forgotten jack", () => {
    room.upsertAttachment(jack);
    room.removeAttachment("att-1");
    // The server may still be finishing that jack's git lookup when the record
    // goes, so its state broadcast can land after attachment_removed.
    room.upsertAttachment({ ...jack, cwd_git: { sha: "d87b3ae", dirty: false } });
    expect(room.attachments).toEqual([]);
  });

  it("still records other jacks, and the same id again on a new line", () => {
    room.upsertAttachment(jack);
    room.removeAttachment("att-1");
    room.upsertAttachment({ ...jack, id: "att-2", name: "terra" });
    expect(room.attachments.map((attachment) => attachment.id)).toEqual(["att-2"]);
    room.leave({ clearRoute: false });
    room.upsertAttachment(jack);
    expect(room.attachments.map((attachment) => attachment.id)).toEqual(["att-1"]);
  });
});

describe("room roster snapshots that were in flight during a removal", () => {
  it("drops a forgotten jack from a resync response that started before the removal", async () => {
    room.conversation = conversation;
    room.upsertAttachment(jack);
    let deliver!: (detail: ConversationDetail) => void;
    const stale = new Promise<ConversationDetail>((resolve) => (deliver = resolve));
    vi.spyOn(api, "conversation").mockReturnValue(stale);
    vi.spyOn(room.history, "catchUp").mockResolvedValue(undefined);

    const resync = room.resync();
    room.removeAttachment("att-1"); // the removal event lands while the fetch is out
    deliver({
      conversation,
      messages: [],
      has_more_messages: false,
      attachments: [jack],
      working: [],
      presence: null,
    });
    await resync;

    expect(room.attachments).toEqual([]);
  });
});
