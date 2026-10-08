import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import BulkArchiveDialog from "./BulkArchiveDialog.svelte";
import { ApiError, api } from "../../lib/api";
import { ArchiveResultSchema, ConversationDetailSchema, ConversationSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

function line(id: string, parentId: string | null) {
  return ConversationSchema.parse({ id, name: id, topic: "", created_at: 1, parent_id: parentId });
}

function archived(id: string) {
  return ArchiveResultSchema.parse({
    ok: true,
    archived: true,
    stopped: [],
    archived_ids: [id],
    conversation: line(id, null),
  });
}

async function confirm(): Promise<void> {
  const input = document.querySelector<HTMLInputElement>(".confirm-form input");
  if (!input) throw new Error("missing confirm input");
  input.value = "confirm";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await vi.waitFor(() => {
    expect(document.querySelector<HTMLButtonElement>(".confirm-form button[type=submit]")?.disabled).toBe(
      false,
    );
  });
  document.querySelector<HTMLFormElement>(".confirm-form")?.requestSubmit();
}

describe("bulk archive dialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    room.conversations = [];
    room.notice = null;
  });

  it("archives each confirmed line once, deepest first, after typing confirm", async () => {
    const lines = [line("root", null), line("kid", "root"), line("solo", null)];
    room.conversations = lines;
    vi.spyOn(api, "conversation").mockImplementation((id) =>
      Promise.resolve(
        ConversationDetailSchema.parse({ conversation: line(id, null), messages: [], attachments: [] }),
      ),
    );
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    vi.spyOn(room, "refreshArchiveIfOpen").mockImplementation(() => undefined);
    const archive = vi
      .spyOn(api, "archiveConversation")
      .mockImplementation((id) => Promise.resolve(archived(id)));
    const close = vi.fn();
    const ondone = vi.fn();
    const dialog = mount(BulkArchiveDialog, { target: document.body, props: { lines, close, ondone } });
    try {
      expect(document.body.textContent).toContain("archive 3 lines");
      await confirm();
      await vi.waitFor(() => {
        expect(close).toHaveBeenCalled();
      });
      expect(archive.mock.calls).toEqual([["kid"], ["root"], ["solo"]]);
      expect(ondone).toHaveBeenCalled();
      expect(room.notice?.message).toBe("3 lines archived");
    } finally {
      await unmount(dialog);
    }
  });

  it("leaves the open line once it is archived", async () => {
    const lines = [line("open", null)];
    room.conversations = lines;
    room.conversation = lines[0] ?? null;
    vi.spyOn(api, "conversation").mockRejectedValue(new Error("offline"));
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    vi.spyOn(room, "refreshArchiveIfOpen").mockImplementation(() => undefined);
    vi.spyOn(api, "archiveConversation").mockResolvedValue(archived("open"));
    const leave = vi.spyOn(room, "leave").mockImplementation(() => undefined);
    const close = vi.fn();
    const dialog = mount(BulkArchiveDialog, { target: document.body, props: { lines, close } });
    try {
      await confirm();
      await vi.waitFor(() => {
        expect(close).toHaveBeenCalled();
      });
      expect(leave).toHaveBeenCalledTimes(1);
    } finally {
      room.conversation = null;
      await unmount(dialog);
    }
  });

  it("stays open on a failure and retries only what is left", async () => {
    const lines = [line("one", null), line("two", null)];
    room.conversations = lines;
    vi.spyOn(api, "conversation").mockRejectedValue(new Error("offline"));
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    vi.spyOn(room, "refreshArchiveIfOpen").mockImplementation(() => undefined);
    const archive = vi
      .spyOn(api, "archiveConversation")
      .mockResolvedValueOnce(archived("one"))
      .mockRejectedValueOnce(new ApiError("line has uncommitted work", 409))
      .mockResolvedValueOnce(archived("two"));
    const close = vi.fn();
    const dialog = mount(BulkArchiveDialog, { target: document.body, props: { lines, close } });
    try {
      await confirm();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("two: line has uncommitted work");
      });
      expect(close).not.toHaveBeenCalled();
      document.querySelector<HTMLFormElement>(".confirm-form")?.requestSubmit();
      await vi.waitFor(() => {
        expect(close).toHaveBeenCalled();
      });
      expect(archive.mock.calls.map(([id]) => id)).toEqual(["one", "two", "two"]);
    } finally {
      await unmount(dialog);
    }
  });
});
