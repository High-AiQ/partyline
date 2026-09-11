import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ManagementDialog from "./ManagementDialog.svelte";
import { api } from "../../lib/api";
import { hierarchyApi } from "../../lib/hierarchy-api";
import { ConversationDetailSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

const detail = ConversationDetailSchema.parse({
  conversation: { id: "child", name: "Child", topic: "", created_at: 1, parent_id: "parent" },
  messages: [],
  attachments: [],
});

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
});

describe("management dialog", () => {
  it("links a parent line and offers no human manager control", async () => {
    vi.spyOn(api, "conversation").mockResolvedValue(detail);
    const saveParent = vi.spyOn(hierarchyApi, "setParent").mockResolvedValue({
      ...detail.conversation,
      parent_id: null,
    });
    vi.spyOn(room, "loadConversations").mockResolvedValue();
    const component = mount(ManagementDialog, {
      target: document.body,
      props: { conversation: detail.conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("#parentLine")).not.toBeNull();
      });
      expect(document.querySelector("#lineManager")).toBeNull();
      expect([...document.querySelectorAll("button")].some((b) => b.textContent === "save manager")).toBe(
        false,
      );
      const select = document.querySelector("#parentLine");
      if (!(select instanceof HTMLSelectElement)) throw new Error("missing parent select");
      select.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      const save = [...document.querySelectorAll("button")].find(
        (button) => button.textContent === "save parent",
      );
      save?.click();
      await vi.waitFor(() => {
        expect(saveParent).toHaveBeenCalledWith("child", null);
      });
    } finally {
      await unmount(component);
    }
  });

  it("does not offer empty replacement values when management failed to load", async () => {
    vi.spyOn(api, "conversation").mockRejectedValue(new Error("offline"));
    const component = mount(ManagementDialog, {
      target: document.body,
      props: { conversation: detail.conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("could not load management");
      });
      expect(document.querySelector("#lineManager")).toBeNull();
      expect(document.querySelector("#parentLine")).toBeNull();
    } finally {
      await unmount(component);
    }
  });
});
