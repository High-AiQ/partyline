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
  attachments: [
    {
      id: "worker",
      conv_id: "child",
      name: "worker",
      adapter: "raw",
      command: ["sh"],
      cwd: "/tmp",
      status: "running",
      last_seen: 0,
      created_at: 1,
    },
  ],
});

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
});

describe("management dialog", () => {
  it("uses attachment identity and saves manager independently of parent", async () => {
    vi.spyOn(api, "conversation").mockResolvedValue(detail);
    vi.spyOn(hierarchyApi, "lead").mockResolvedValue({ attachment_id: "worker" });
    const saveLead = vi.spyOn(hierarchyApi, "setLead").mockResolvedValue({ attachment_id: null });
    const saveParent = vi.spyOn(hierarchyApi, "setParent");
    vi.spyOn(room, "loadConversations").mockResolvedValue();
    const component = mount(ManagementDialog, {
      target: document.body,
      props: { conversation: detail.conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("#lineManager")).not.toBeNull();
      });
      const select = document.querySelector("#lineManager");
      if (!(select instanceof HTMLSelectElement)) throw new Error("missing manager select");
      expect(select.value).toBe("worker");
      select.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      const save = [...document.querySelectorAll("button")].find(
        (button) => button.textContent === "save manager",
      );
      save?.click();
      await vi.waitFor(() => {
        expect(saveLead).toHaveBeenCalledWith("child", null);
      });
      expect(saveParent).not.toHaveBeenCalled();
    } finally {
      await unmount(component);
    }
  });

  it("does not offer empty replacement values when management failed to load", async () => {
    vi.spyOn(api, "conversation").mockRejectedValue(new Error("offline"));
    vi.spyOn(hierarchyApi, "lead").mockResolvedValue({ attachment_id: null });
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
