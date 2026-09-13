import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import DeleteLineDialog from "./DeleteLineDialog.svelte";
import { api } from "../../lib/api";
import { ArchiveResultSchema, ConversationDetailSchema, ConversationSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

function line(id: string, parentId: string | null) {
  return ConversationSchema.parse({ id, name: id, topic: "", created_at: 1, parent_id: parentId });
}

function detail(id: string) {
  return ConversationDetailSchema.parse({
    conversation: line(id, null),
    messages: [],
    attachments: [],
  });
}

describe("delete line dialog with child lines", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("offers the whole tree in one checkbox and archives with it", async () => {
    room.conversations = [line("root", null), line("kid", "root"), line("grandkid", "kid")];
    vi.spyOn(api, "conversation").mockImplementation((id) => Promise.resolve(detail(id)));
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    vi.spyOn(room, "refreshArchiveIfOpen").mockImplementation(() => undefined);
    const archive = vi.spyOn(api, "archiveConversation").mockResolvedValue(
      ArchiveResultSchema.parse({
        ok: true,
        archived: true,
        stopped: [],
        archived_ids: ["grandkid", "kid", "root"],
        conversation: line("root", null),
      }),
    );
    const dialog = mount(DeleteLineDialog, {
      target: document.body,
      props: { conversation: line("root", null), close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".dialog-check input")).not.toBeNull();
      });
      expect(document.body.textContent).toContain("also delete its 2 child lines");
      const box = document.querySelector(".dialog-check input");
      if (!(box instanceof HTMLInputElement)) throw new Error("no checkbox");
      box.click();
      const input = document.querySelector("#confirmPhrase");
      if (!(input instanceof HTMLInputElement)) throw new Error("no confirm input");
      input.value = "root";
      input.dispatchEvent(new Event("input"));
      const button = [...document.querySelectorAll("button")].find((b) =>
        b.textContent.includes("delete line"),
      );
      if (!button) throw new Error("no delete button");
      await vi.waitFor(() => {
        expect(button.disabled).toBe(false);
      });
      button.click();
      await vi.waitFor(() => {
        expect(archive).toHaveBeenCalledWith("root", true);
      });
    } finally {
      void unmount(dialog);
    }
  });
});
