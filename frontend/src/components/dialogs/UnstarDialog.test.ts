import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import UnstarDialog from "./UnstarDialog.svelte";
import { ConversationSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";
import * as starApi from "../../lib/conversation-star-api";

const line = ConversationSchema.parse({
  id: "fav",
  name: "Favorite Line",
  topic: "",
  created_at: 1,
  starred: true,
});

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll("button")].find((item) => item.textContent === label);
  if (!found) throw new Error(`missing ${label}`);
  return found;
}

function open(close = vi.fn()) {
  room.conversations = [line];
  const dialog = mount(UnstarDialog, { target: document.body, props: { conversation: line, close } });
  return { dialog, close };
}

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
  room.notice = null;
  document.body.replaceChildren();
});

describe("unstar confirmation dialog", () => {
  it("asks to remove the named line from favorites, with Cancel focused", async () => {
    const { dialog } = open();
    await tick();
    expect(document.querySelector("[role=dialog]")?.getAttribute("aria-label")).toBe(
      "Remove from favorites?",
    );
    expect(document.body.textContent).toContain("Favorite Line");
    expect(document.activeElement).toBe(button("Cancel"));
    await unmount(dialog);
  });

  it("Cancel leaves the line starred", async () => {
    const set = vi.spyOn(starApi, "setConversationStar");
    const { dialog, close } = open();
    button("Cancel").click();
    expect(close).toHaveBeenCalledOnce();
    expect(set).not.toHaveBeenCalled();
    await unmount(dialog);
  });

  it("a click outside leaves the line starred, and a click inside does not close", async () => {
    const set = vi.spyOn(starApi, "setConversationStar");
    const { dialog, close } = open();
    const overlay = document.querySelector<HTMLElement>(".overlay");
    document.querySelector<HTMLElement>(".modal")?.click();
    expect(close).not.toHaveBeenCalled();
    overlay?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    overlay?.click();
    expect(close).toHaveBeenCalledOnce();
    expect(set).not.toHaveBeenCalled();
    await unmount(dialog);
  });

  it("Remove unstars the line and closes", async () => {
    const set = vi.spyOn(starApi, "setConversationStar").mockResolvedValue({ ok: true, starred: false });
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    const { dialog, close } = open();
    button("Remove").click();
    await vi.waitFor(() => {
      expect(close).toHaveBeenCalledOnce();
    });
    expect(set).toHaveBeenCalledWith("fav", false);
    await unmount(dialog);
  });

  it("shows the usual error notice when the request fails", async () => {
    vi.spyOn(starApi, "setConversationStar").mockRejectedValue(new Error("boom"));
    const { dialog, close } = open();
    button("Remove").click();
    await vi.waitFor(() => {
      expect(close).toHaveBeenCalledOnce();
    });
    expect(room.notice).toMatchObject({ message: "boom" });
    await unmount(dialog);
  });

  it("does not star the line back if it was already unstarred elsewhere", async () => {
    const set = vi.spyOn(starApi, "setConversationStar");
    const { dialog, close } = open();
    room.conversations = [{ ...line, starred: false }];
    button("Remove").click();
    await vi.waitFor(() => {
      expect(close).toHaveBeenCalledOnce();
    });
    expect(set).not.toHaveBeenCalled();
    await unmount(dialog);
  });
});
