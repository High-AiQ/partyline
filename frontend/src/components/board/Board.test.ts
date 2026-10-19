import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Board from "./Board.svelte";
import ManagementDialog from "../dialogs/ManagementDialog.svelte";
import { api } from "../../lib/api";
import { hierarchyApi } from "../../lib/hierarchy-api";
import { ConversationDetailSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

const conversation = {
  id: "line",
  name: "line",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 1,
};

const attachment = {
  id: "captain-attachment",
  conv_id: "line",
  name: "worker",
  adapter: "raw",
  command: ["worker"],
  cwd: "/tmp",
  status: "running" as const,
  last_seen: 1,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
};

afterEach(() => {
  vi.restoreAllMocks();
  room.conversation = null;
  room.attachments = [];
  room.conversations = [];
  room.captains = {};
  document.body.replaceChildren();
});

describe("Board captain status", () => {
  it("updates the visible card immediately when management appoints a captain", async () => {
    const detail = ConversationDetailSchema.parse({ conversation, messages: [], attachments: [attachment] });
    vi.spyOn(api, "conversation").mockResolvedValue(detail);
    vi.spyOn(hierarchyApi, "lead").mockResolvedValue({ attachment_id: null });
    const appoint = vi.spyOn(hierarchyApi, "appoint").mockResolvedValue({
      attachment_id: attachment.id,
    });
    room.conversation = conversation;
    room.attachments = [attachment];

    const board = mount(Board, { target: document.body, props: { onmention: vi.fn() } });
    const dialog = mount(ManagementDialog, {
      target: document.body,
      props: { conversation, close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("#captain")).not.toBeNull();
      });
      const select = document.querySelector("#captain");
      if (!(select instanceof HTMLSelectElement)) throw new Error("missing captain select");
      select.value = attachment.id;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      document.querySelector<HTMLButtonElement>("#appointCaptain")?.click();
      await vi.waitFor(() => {
        expect(appoint).toHaveBeenCalledWith("line", attachment.id);
        expect(document.querySelector(".captain-badge")).not.toBeNull();
      });
    } finally {
      await unmount(dialog);
      await unmount(board);
    }
  });
});

it("hides task staffing controls using refreshed rail metadata", async () => {
  vi.spyOn(hierarchyApi, "lead").mockResolvedValue({ attachment_id: null });
  room.conversation = conversation;
  room.conversations = [conversation];
  const board = mount(Board, { target: document.body, props: { onmention: vi.fn() } });
  try {
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("patch in a process");
    });
    room.conversations = [{ ...conversation, task_status: "blocked" }];
    await vi.waitFor(() => {
      expect(document.body.textContent).not.toContain("patch in a process");
    });
    expect(document.querySelector("#jacks")).not.toBeNull();
    expect(document.querySelector("#attach")).toBeNull();
    room.conversations = [conversation];
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("patch in a process");
    });
  } finally {
    await unmount(board);
  }
});
