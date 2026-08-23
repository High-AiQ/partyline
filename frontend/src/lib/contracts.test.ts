import { describe, expect, it } from "vitest";
import {
  AuthTokenResponseSchema,
  HandleSchema,
  AdapterSchema,
  ClaimSchema,
  ConversationDetailSchema,
  FileRefSchema,
  TaskSchema,
  VersionInfoSchema,
  WireEventSchema,
  WireReattachCommandSchema,
} from "./contracts";

const offer = {
  type: "reattach_offer",
  conversation_id: "line",
  token: "offer-token",
  attachments: [{ id: "att-1", name: "sol", adapter: "codex" }],
  debrief: "Continue the review.",
};

describe("auth contracts", () => {
  it("accepts the issued JWT pair with its authenticated user", () => {
    const response = {
      access_token: "access",
      refresh_token: "refresh",
      token_type: "bearer",
      user: { id: 1, email: "greg@example.com", handle: "greg" },
    };
    expect(AuthTokenResponseSchema.parse(response)).toEqual(response);
  });

  it("rejects handles outside the shared server syntax", () => {
    expect(HandleSchema.safeParse("sol.review").success).toBe(true);
    expect(HandleSchema.safeParse("two words").success).toBe(false);
    expect(HandleSchema.safeParse("ab").success).toBe(false);
  });
});

describe("wire events with server-omitted null fields", () => {
  it("defaults an omitted instance label and keeps a configured one", () => {
    expect(VersionInfoSchema.parse({ version: "0.39.0", build: "abc" }).instance_name).toBeNull();
    const hello = WireEventSchema.parse({
      type: "hello",
      conversation_id: "line",
      handle: "greg",
      version: "0.39.0",
      instance_name: "Cockpit",
    });
    expect(hello.type === "hello" && hello.instance_name).toBe("Cockpit");
  });

  it("accepts the unforgeable working event shape", () => {
    const event = { type: "working" as const, attachment_id: "att-1", working: true };
    expect(WireEventSchema.parse(event)).toEqual({
      ...event,
      phase: "working",
      completion: "none",
      since: 0,
      turn: 0,
      revision: 0,
    });
  });

  // `broadcast()` serializes with `exclude_none=True`, so a None field is
  // omitted on the wire even though REST spells it `null`. These payloads are
  // exactly what the server sends; rejecting them stopped the tab with
  // "client/server protocol mismatch" every time a fresh process was added.
  it("reads a fresh attachment without cli_session as cli_session null", () => {
    const event = WireEventSchema.parse({
      type: "attachment",
      attachment: {
        id: "att-1",
        conv_id: "line",
        name: "sol",
        adapter: "codex",
        command: ["codex"],
        cwd: "/home/user/project",
        status: "starting",
        last_seen: 0,
        created_at: 1754700000,
      },
    });
    if (event.type !== "attachment") throw new Error("expected attachment event");
    expect(event.attachment.cli_session).toBeNull();
    expect(event.attachment.cwd_git).toBeNull();
  });

  it("reads an unarchived conversation without archived_at as archived_at null", () => {
    const event = WireEventSchema.parse({
      type: "conversation",
      conversation: {
        id: "line",
        name: "add muse to partyline",
        topic: "",
        created_at: 1754700000,
      },
    });
    if (event.type !== "conversation") throw new Error("expected conversation event");
    expect(event.conversation.archived_at).toBeNull();
  });

  it("still accepts the REST spelling, where the empty field is null", () => {
    const event = WireEventSchema.parse({
      type: "attachment",
      attachment: {
        id: "att-1",
        conv_id: "line",
        name: "sol",
        adapter: "codex",
        command: ["codex"],
        cwd: "/home/user/project",
        status: "running",
        last_seen: 4,
        created_at: 1754700000,
        cli_session: null,
        cwd_git: { sha: "d87b3ae", dirty: true },
      },
    });
    if (event.type !== "attachment") throw new Error("expected attachment event");
    expect(event.attachment.cli_session).toBeNull();
    expect(event.attachment.cwd_git).toEqual({ sha: "d87b3ae", dirty: true });
    expect(event.attachment.follow).toBe(false);
  });
});

describe("conversation detail compatibility", () => {
  it("defaults working ids for servers predating wake receipts", () => {
    const detail = ConversationDetailSchema.parse({
      conversation: { id: "line", name: "line", topic: "", created_at: 1 },
      messages: [],
      attachments: [],
    });
    expect(detail.working).toEqual([]);
    expect(detail.presence).toBeNull();
  });

  it("accepts revisioned presence including idle tombstones", () => {
    const detail = ConversationDetailSchema.parse({
      conversation: { id: "line", name: "line", topic: "", created_at: 1 },
      messages: [],
      attachments: [],
      working: [],
      presence: [
        {
          id: "att-1",
          phase: "idle",
          completion: "receipt",
          since: 2,
          turn: 3,
          revision: 9,
        },
      ],
    });
    expect(detail.presence?.[0]).toMatchObject({ id: "att-1", phase: "idle", revision: 9 });
  });
});

describe("coordination contracts", () => {
  it("parses claims and tasks at the browser boundary", () => {
    expect(
      ClaimSchema.parse({
        id: "claim-1",
        owner: "sol",
        paths: ["frontend/**"],
        created_at: 1,
        expires_at: 2,
      }),
    ).toMatchObject({ owner: "sol", paths: ["frontend/**"] });

    expect(
      TaskSchema.parse({
        id: 1,
        body: "prove the working receipt",
        status: "open",
        owner: null,
        created_at: 1,
        updated_at: 1,
      }),
    ).toMatchObject({ status: "open", owner: null });
  });
});

describe("file message contracts", () => {
  it("defaults files for messages from servers predating the file field", () => {
    const event = WireEventSchema.parse({
      type: "message",
      message: {
        id: 1,
        conv_id: "line",
        sender: "greg",
        sender_type: "human",
        body: "hello",
        created_at: 1,
      },
    });
    if (event.type !== "message") throw new Error("expected message event");
    expect(event.message.files).toEqual([]);
  });

  it("defaults absent slim metadata for stored events from v0.32", () => {
    const parsed = FileRefSchema.parse({
      id: "image-1",
      kind: "image",
      mime: "image/png",
      width: 600,
      height: 600,
      bytes: 42,
      thumb: { mime: "image/webp", width: 512, height: 512 },
      urls: { original: "/original", thumb: "/thumb" },
    });

    expect(parsed.filename).toBeNull();
    expect(parsed.slim).toBeNull();
    expect(parsed.urls.slim).toBeNull();
    expect(parsed.thumb?.bytes).toBeNull();
  });

  it("reads a non-image file with the wire's omitted null fields", () => {
    // `broadcast()` serializes with exclude_none=True, so filename,
    // width/height, and the derived tiers are absent rather than null.
    const parsed = FileRefSchema.parse({
      id: "file-1",
      kind: "file",
      mime: "application/pdf",
      bytes: 2048,
      urls: { original: "/original", thumb: "/original" },
    });

    expect(parsed.filename).toBeNull();
    expect(parsed.width).toBeNull();
    expect(parsed.height).toBeNull();
    expect(parsed.thumb).toBeNull();
  });

  it("rejects a kind outside the server's vocabulary", () => {
    const parsed = FileRefSchema.safeParse({
      id: "file-1",
      kind: "archive",
      mime: "application/zip",
      bytes: 10,
      urls: { original: "/original", thumb: "/original" },
    });

    expect(parsed.success).toBe(false);
  });
});

describe("restart wire contracts", () => {
  it("accepts the named same-line offer payload", () => {
    expect(WireEventSchema.parse(offer)).toEqual(offer);
  });

  it("rejects an offer without the token that binds the decision", () => {
    const missingToken = {
      type: offer.type,
      conversation_id: offer.conversation_id,
      attachments: offer.attachments,
      debrief: offer.debrief,
    };

    expect(() => WireEventSchema.parse(missingToken)).toThrow();
  });

  it("allows only an explicit accept or cancel decision", () => {
    expect(
      WireReattachCommandSchema.parse({
        type: "reattach",
        token: "offer-token",
        action: "accept",
      }),
    ).toEqual({ type: "reattach", token: "offer-token", action: "accept" });
    expect(() =>
      WireReattachCommandSchema.parse({
        type: "reattach",
        token: "offer-token",
        action: "later",
      }),
    ).toThrow();
  });
});

describe("adapter override metadata", () => {
  const adapter = {
    id: "codex",
    command: ["codex"],
    capabilities: {},
  };

  it("defaults absent override metadata for older servers", () => {
    expect(AdapterSchema.parse(adapter).overrides_bundled).toBe(false);
  });

  it("preserves an imported adapter's bundled override marker", () => {
    expect(AdapterSchema.parse({ ...adapter, overrides_bundled: true }).overrides_bundled).toBe(true);
  });

  it("defaults a missing update command to null", () => {
    expect(AdapterSchema.parse(adapter).update_command).toBeNull();
  });

  it("keeps a declared update command", () => {
    expect(AdapterSchema.parse({ ...adapter, update_command: ["codex", "update"] }).update_command).toEqual([
      "codex",
      "update",
    ]);
  });

  it("defaults compact support and keeps an exact paste string", () => {
    expect(AdapterSchema.parse(adapter).compact_paste).toBeNull();
    expect(AdapterSchema.parse({ ...adapter, compact_paste: "/summarize\n" }).compact_paste).toBe(
      "/summarize\n",
    );
  });

  it("defaults and keeps normalized completion for human follow controls", () => {
    expect(AdapterSchema.parse(adapter).completion).toBe("none");
    expect(AdapterSchema.parse({ ...adapter, completion: "receipt" }).completion).toBe("receipt");
  });
});
