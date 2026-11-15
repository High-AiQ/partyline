import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import WindowAccessLine from "./WindowAccessLine.svelte";
import { screenApi } from "../lib/screen-api";
import { ConversationSchema } from "../lib/conversation-contracts";
import { room } from "../state/room.svelte.js";

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
  document.body.replaceChildren();
});

it("authorizes a selected root, clears scope, and restores the confirmed binding on error", async () => {
  room.conversations = [
    ConversationSchema.parse({ id: "alpha", name: "Alpha", topic: "", created_at: 1 }),
    ConversationSchema.parse({ id: "beta", name: "Beta", topic: "", created_at: 1 }),
  ];
  const save = vi.spyOn(screenApi, "authorizeWindowLine").mockResolvedValue({ ok: true });
  const component = mount(WindowAccessLine, {
    target: document.body,
    props: {
      device: {
        id: "computer",
        name: "Desk",
        os: "test",
        online: false,
        monitors: [],
        window_access_line: "alpha",
      },
    },
  });
  await tick();
  const select = document.querySelector("select");
  if (!select) throw new Error("Missing authorization selector");
  expect(select.value).toBe("alpha");
  select.value = "beta";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await tick();
  expect(save).toHaveBeenLastCalledWith("computer", "beta");
  select.value = "";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await tick();
  expect(save).toHaveBeenLastCalledWith("computer", null);
  save.mockRejectedValueOnce(new Error("denied"));
  select.value = "beta";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await tick();
  await tick();
  expect(select.value).toBe("alpha");
  expect(document.querySelector('[data-save-phase="error"]')?.textContent).toContain("denied");
  await unmount(component);
});
