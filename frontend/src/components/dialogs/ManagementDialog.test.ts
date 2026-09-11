import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ManagementDialog from "./ManagementDialog.svelte";
import { api } from "../../lib/api";
import { hierarchyApi } from "../../lib/hierarchy-api";
import { ConversationDetailSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

function detailWith(parentId: string | null) {
  return ConversationDetailSchema.parse({
    conversation: {
      id: "child",
      name: "Child",
      topic: "",
      created_at: 1,
      parent_id: parentId,
    },
    messages: [],
    attachments: [],
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
  room.conversation = null;
});

describe("management dialog parent control", () => {
  it("offers only unlink once a parent is set, and never re-points it", async () => {
    vi.spyOn(api, "conversation").mockResolvedValue(detailWith("parent"));
    const saveParent = vi.spyOn(hierarchyApi, "setParent").mockResolvedValue({
      id: "child",
      name: "Child",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
      parent_id: null,
    });
    vi.spyOn(room, "loadConversations").mockResolvedValue();
    const component = mount(ManagementDialog, {
      target: document.body,
      props: { conversation: detailWith("parent").conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("unlink parent");
      });
      expect(document.querySelector("#parentLine")).toBeNull();
      expect([...document.querySelectorAll("button")].some((b) => b.textContent === "save parent")).toBe(
        false,
      );
      const unlink = [...document.querySelectorAll("button")].find(
        (button) => button.textContent === "unlink parent",
      );
      unlink?.click();
      await vi.waitFor(() => {
        expect(saveParent).toHaveBeenCalledWith("child", null);
      });
    } finally {
      await unmount(component);
    }
  });

  it("sets a parent for an independent line", async () => {
    vi.spyOn(api, "conversation").mockResolvedValue(detailWith(null));
    const saveParent = vi.spyOn(hierarchyApi, "setParent").mockResolvedValue({
      id: "child",
      name: "Child",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
      parent_id: "parent",
    });
    vi.spyOn(room, "loadConversations").mockResolvedValue();
    room.conversations = [detailWith(null).conversation].map((c) => ({ ...c, id: "parent", name: "Parent" }));
    const component = mount(ManagementDialog, {
      target: document.body,
      props: { conversation: detailWith(null).conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("#parentLine")).not.toBeNull();
      });
      const select = document.querySelector("#parentLine");
      if (!(select instanceof HTMLSelectElement)) throw new Error("missing parent select");
      select.value = "parent";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      const save = [...document.querySelectorAll("button")].find(
        (button) => button.textContent === "save parent",
      );
      save?.click();
      await vi.waitFor(() => {
        expect(saveParent).toHaveBeenCalledWith("child", "parent");
      });
    } finally {
      await unmount(component);
    }
  });

  it("does not offer empty replacement values when management failed to load", async () => {
    vi.spyOn(api, "conversation").mockRejectedValue(new Error("offline"));
    const component = mount(ManagementDialog, {
      target: document.body,
      props: { conversation: detailWith("parent").conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("could not load management");
      });
      expect(document.querySelector("#parentLine")).toBeNull();
    } finally {
      await unmount(component);
    }
  });
});
