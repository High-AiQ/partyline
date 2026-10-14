import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import BridgeSection from "./BridgeSection.svelte";
import { api } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { bridgeApi, type Bridge } from "../../lib/bridge-api";
import { ConversationDetailSchema } from "../../lib/contracts";
import type { Attachment } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

const line = (id: string, name: string, parent_id: string | null = null) => ({
  id,
  name,
  topic: "",
  created_at: 1,
  parent_id,
  archived_at: null,
  live_count: 1,
});
const process = (id: string, conv: string, name: string): Attachment => ({
  id,
  conv_id: conv,
  name,
  adapter: "codex",
  command: [],
  cwd: "/",
  status: "running",
  last_seen: 0,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
});
const opened: Bridge = {
  id: "b1",
  opened_at: 1_700_000_000,
  opened_by: "greg",
  sides: [
    { conv_id: "x", conv_name: "3d game", attachment_id: "x-amb", name: "sonnet" },
    { conv_id: "y", conv_name: "tool", attachment_id: "y-amb", name: "fable" },
  ],
};

function mountSection() {
  return mount(BridgeSection, { target: document.body, props: { conversation: line("x", "3d game") } });
}
const byId = (id: string): HTMLSelectElement => {
  const node = document.getElementById(id);
  if (!(node instanceof HTMLSelectElement)) throw new Error(`missing #${id}`);
  return node;
};
const choose = (id: string, value: string) => {
  const select = byId(id);
  select.value = value;
  select.dispatchEvent(new Event("change", { bubbles: true }));
};
const button = (label: string) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent === label);

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
  room.attachments = [];
});

describe("bridge section", () => {
  it("offers only other trees and opens a bridge between the two chosen ambassadors", async () => {
    room.conversations = [line("x", "3d game"), line("kid", "kid of x", "x"), line("y", "tool")];
    room.attachments = [process("x-amb", "x", "sonnet")];
    vi.spyOn(bridgeApi, "forLine").mockResolvedValue(null);
    vi.spyOn(api, "conversation").mockResolvedValue(
      ConversationDetailSchema.parse({
        conversation: line("y", "tool"),
        messages: [],
        attachments: [process("y-amb", "y", "fable")],
      }),
    );
    const open = vi.spyOn(bridgeApi, "open").mockResolvedValue(opened);
    const section = mountSection();
    try {
      await vi.waitFor(() => {
        expect(document.getElementById("bridgeLine")).not.toBeNull();
      });
      const offered = [...byId("bridgeLine").options].map((o) => o.value);
      expect(offered).toEqual(["", "y"]); // not itself, not its child
      expect(button("open bridge")?.disabled).toBe(true);
      choose("bridgeMine", "x-amb");
      choose("bridgeLine", "y");
      await vi.waitFor(() => {
        expect(byId("bridgeTheirs").options.length).toBe(2);
      });
      choose("bridgeTheirs", "y-amb");
      await vi.waitFor(() => {
        expect(button("open bridge")?.disabled).toBe(false);
      });
      button("open bridge")?.click();
      await vi.waitFor(() => {
        expect(open).toHaveBeenCalledWith(
          { conv_id: "x", attachment_id: "x-amb" },
          { conv_id: "y", attachment_id: "y-amb" },
        );
      });
      await vi.waitFor(() => {
        expect(button("close bridge")).toBeDefined();
      });
      expect(document.body.textContent).toContain("fable on «tool»");
    } finally {
      await unmount(section);
    }
  });

  it("shows a 409 reason in the status line", async () => {
    room.conversations = [line("x", "3d game"), line("y", "tool")];
    room.attachments = [process("x-amb", "x", "sonnet")];
    vi.spyOn(bridgeApi, "forLine").mockResolvedValue(null);
    vi.spyOn(api, "conversation").mockResolvedValue(
      ConversationDetailSchema.parse({
        conversation: line("y", "tool"),
        messages: [],
        attachments: [process("y-amb", "y", "fable")],
      }),
    );
    vi.spyOn(bridgeApi, "open").mockRejectedValue(
      new ApiError("line «tool» already has an open bridge", 409),
    );
    const section = mountSection();
    try {
      await vi.waitFor(() => {
        expect(document.getElementById("bridgeLine")).not.toBeNull();
      });
      choose("bridgeMine", "x-amb");
      choose("bridgeLine", "y");
      await vi.waitFor(() => {
        expect(byId("bridgeTheirs").options.length).toBe(2);
      });
      choose("bridgeTheirs", "y-amb");
      await vi.waitFor(() => {
        expect(button("open bridge")?.disabled).toBe(false);
      });
      button("open bridge")?.click();
      await vi.waitFor(() => {
        expect(document.querySelector(".line-status.error")?.textContent).toContain(
          "already has an open bridge",
        );
      });
    } finally {
      await unmount(section);
    }
  });

  it("closes an open bridge and reads its log on demand", async () => {
    vi.spyOn(bridgeApi, "forLine").mockResolvedValue(opened);
    const log = vi
      .spyOn(bridgeApi, "log")
      .mockResolvedValue([
        { id: 5, conv_id: "x", sender: "sonnet", body: "the schema changed", created_at: 1_700_000_001 },
      ]);
    const close = vi
      .spyOn(bridgeApi, "close")
      .mockResolvedValue({ ...opened, closed_at: 2, closed_by: "greg" });
    const section = mountSection();
    try {
      await vi.waitFor(() => {
        expect(button("close bridge")).toBeDefined();
      });
      expect(document.body.textContent).toContain("sonnet on «3d game»");
      const details = document.querySelector("details");
      if (!details) throw new Error("no log disclosure");
      details.open = true;
      details.dispatchEvent(new Event("toggle"));
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("the schema changed");
      });
      expect(log).toHaveBeenCalledWith("b1");
      button("close bridge")?.click();
      await vi.waitFor(() => {
        expect(close).toHaveBeenCalledWith("b1");
      });
      await vi.waitFor(() => {
        expect(document.getElementById("bridgeLine")).not.toBeNull();
      });
      expect(document.body.textContent).toContain("bridge closed");
    } finally {
      await unmount(section);
    }
  });
});
