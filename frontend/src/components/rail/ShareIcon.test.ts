import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import ShareIcon from "./ShareIcon.svelte";
import ConversationList from "./ConversationList.svelte";
import { screenStatus } from "../../state/screen-status.svelte";
import { room } from "../../state/room.svelte.js";

afterEach(() => {
  screenStatus.indicators = [];
  room.conversations = [];
  localStorage.clear();
  document.body.replaceChildren();
});
it("draws outlined availability and filled green activity using the same computer glyph", async () => {
  for (const kind of ["standing", "window", "screen"]) {
    const component = mount(ShareIcon, {
      target: document.body,
      props: { indicators: [{ conv_id: "a", device_name: "Desk", kind, label: kind }] },
    });
    await tick();
    expect(document.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(kind);
    expect(document.querySelector("rect")?.getAttribute("fill")).toBe(
      kind === "standing" ? "none" : "currentColor",
    );
    expect(document.querySelector(".text-green") !== null).toBe(kind !== "standing");
    await unmount(component);
  }
  const empty = mount(ShareIcon, { target: document.body, props: { indicators: [] } });
  await tick();
  expect(document.querySelector("svg")).toBeNull();
  await unmount(empty);
});
it("renders server-derived inherited availability on sublines and updates live to activity", async () => {
  const base = { topic: "", created_at: 1, live_count: 1, archived_at: null };
  room.conversations = [
    { ...base, id: "alpha", name: "Alpha" },
    { ...base, id: "child", name: "Child", parent_id: "alpha" },
  ];
  room.conversation = room.conversations[1] ?? null;
  screenStatus.indicators = ["alpha", "child"].map((conv_id) => ({
    conv_id,
    device_name: "Desk",
    kind: "standing",
    label: "Desk window access available",
  }));
  const list = mount(ConversationList, {
    target: document.body,
    props: { onmanagement: vi.fn(), onrename: vi.fn(), oncloseprocesses: vi.fn(), ondelete: vi.fn() },
  });
  await tick();
  expect(document.querySelectorAll('[data-state="available"]')).toHaveLength(2);
  screenStatus.indicators = [
    ...screenStatus.indicators,
    { conv_id: "child", device_name: "Desk", kind: "window", label: "Editor window" },
  ];
  await tick();
  expect(document.querySelectorAll('[data-state="available"]')).toHaveLength(1);
  expect(document.querySelectorAll('[data-state="active"]')).toHaveLength(1);
  screenStatus.indicators = [];
  await tick();
  expect(document.querySelector(".share-icon")).toBeNull();
  await unmount(list);
  room.conversation = null;
});
