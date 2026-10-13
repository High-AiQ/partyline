import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import WriteSetGrantApprovalDialog from "./WriteSetGrantApprovalDialog.svelte";
import { writeSetApi } from "../../lib/write-set-api";
import { room } from "../../state/room.svelte.js";
import { writeSet } from "../../state/write-set.svelte.js";

function open(path: string): void {
  room.conversation = { id: "line" } as typeof room.conversation;
  writeSet.apply({
    id: "abc",
    conversation_id: "line",
    path,
    requester: "astra",
    created_at: 1,
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll("button")].find((b) => b.textContent.includes(label));
  if (!found) throw new Error(`no button ${label}`);
  return found;
}

describe("write-set grant approval dialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    writeSet.apply(null);
    room.conversation = null;
    document.body.innerHTML = "";
  });

  it("offers managed or unrestricted docker access and says what each means", async () => {
    open("/var/run/docker.sock");
    const approve = vi.spyOn(writeSetApi, "approve").mockResolvedValue({ request: null });
    const dialog = mount(WriteSetGrantApprovalDialog, { target: document.body, props: { close: vi.fn() } });
    try {
      const text = document.querySelector("[data-testid=docker-modes]")?.textContent ?? "";
      expect(text).toContain("Managed");
      expect(text).toContain("root-equivalent");
      button("approve unrestricted").click();
      await vi.waitFor(() => {
        expect(approve).toHaveBeenCalledWith("line", "abc", "unrestricted");
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("approves docker access as managed by default", async () => {
    open("/run/docker.sock");
    const approve = vi.spyOn(writeSetApi, "approve").mockResolvedValue({ request: null });
    const dialog = mount(WriteSetGrantApprovalDialog, { target: document.body, props: { close: vi.fn() } });
    try {
      button("approve managed").click();
      await vi.waitFor(() => {
        expect(approve).toHaveBeenCalledWith("line", "abc", "managed");
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("shows no docker choice for an ordinary path", async () => {
    open("/repo/shared");
    const approve = vi.spyOn(writeSetApi, "approve").mockResolvedValue({ request: null });
    const dialog = mount(WriteSetGrantApprovalDialog, { target: document.body, props: { close: vi.fn() } });
    try {
      expect(document.querySelector("[data-testid=docker-modes]")).toBeNull();
      expect(document.body.textContent).not.toContain("approve unrestricted");
      button("approve grant").click();
      await vi.waitFor(() => {
        expect(approve).toHaveBeenCalledWith("line", "abc", undefined);
      });
    } finally {
      await unmount(dialog);
    }
  });
});
