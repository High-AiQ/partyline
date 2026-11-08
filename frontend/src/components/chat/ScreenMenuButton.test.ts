import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import ScreenMenuButton from "./ScreenMenuButton.svelte";
import { room } from "../../state/room.svelte.js";
import { screenStatus } from "../../state/screen-status.svelte.js";

function required<T>(value: T | null | undefined): T {
  if (value == null) throw new Error("Missing control");
  return value;
}

afterEach(() => {
  room.screenShare = null;
  document.body.replaceChildren();
});

it("opens the menu, navigates with arrows, and returns focus on Escape or outside click", async () => {
  const component = mount(ScreenMenuButton, {
    target: document.body,
    props: { error: "", online: true, onbegin: vi.fn() },
  });
  const trigger = required(document.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]'));
  await tick();
  trigger.focus();
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
  await tick();
  await tick();
  const items = document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(document.activeElement).toBe(items[0]);
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
  expect(document.activeElement).toBe(items[1]);
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  await tick();
  expect(document.activeElement).toBe(trigger);
  expect(document.querySelector('[role="menu"]')).toBeNull();
  trigger.click();
  await tick();
  await tick();
  document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
  await tick();
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await unmount(component);
});

it("opens sharing or starts a walkthrough, and blocks recording during a share", async () => {
  const begin = vi.fn();
  const component = mount(ScreenMenuButton, {
    target: document.body,
    props: { error: "", online: true, onbegin: begin },
  });
  const trigger = required(document.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]'));
  const previous = screenStatus.openPicker;
  trigger.click();
  await tick();
  required(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')[0]).click();
  await tick();
  expect(screenStatus.openPicker).toBe(previous + 1);
  trigger.click();
  await tick();
  required(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')[1]).click();
  await tick();
  expect(begin).toHaveBeenCalledOnce();
  room.screenShare = {
    share_id: "s",
    handle: "a",
    device_name: "desk",
    status: "active",
    region: { x: 0, y: 0, width: 1, height: 1 },
  };
  trigger.click();
  await tick();
  const record = required(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')[1]);
  expect(record.getAttribute("aria-disabled")).toBe("true");
  expect(document.getElementById(record.getAttribute("aria-describedby") ?? "")?.textContent).toContain(
    "Stop the live share",
  );
  record.click();
  expect(begin).toHaveBeenCalledOnce();
  await unmount(component);
});

it("closes on Tab without stealing focus on a later Escape", async () => {
  const component = mount(ScreenMenuButton, {
    target: document.body,
    props: { error: "", online: true, onbegin: vi.fn() },
  });
  const other = document.createElement("button");
  document.body.append(other);
  const trigger = required(document.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]'));
  await tick();
  trigger.click();
  await tick();
  await tick();
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab" }));
  other.focus();
  await tick();
  expect(document.querySelector('[role="menu"]')).toBeNull();
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  expect(document.activeElement).toBe(other);
  await unmount(component);
});
