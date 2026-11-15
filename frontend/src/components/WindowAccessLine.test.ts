import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import WindowAccessLine from "./WindowAccessLine.svelte";
import ComputersSection from "./settings/sections/ComputersSection.svelte";
import { screenApi, type ScreenDevice } from "../lib/screen-api";
import { screenStatus } from "../state/screen-status.svelte";
import { room } from "../state/room.svelte.js";

const device: ScreenDevice = {
  id: "computer",
  name: "Desk",
  os: "test",
  online: true,
  monitors: [],
  window_access_lines: ["alpha"],
};
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  room.conversations = [];
  screenStatus.devices = [];
  document.body.replaceChildren();
});
async function settle(): Promise<void> {
  await tick();
  await tick();
}
function options() {
  return vi.spyOn(screenApi, "windowLineOptions").mockResolvedValue({
    lines: [
      { id: "alpha", name: "Alpha" },
      { id: "beta", name: "Beta" },
    ],
  });
}
it("adds and removes lines through the plural API, keeping confirmed chips on failure", async () => {
  vi.useFakeTimers();
  options();
  const save = vi.spyOn(screenApi, "authorizeWindowLines").mockResolvedValue({ ok: true });
  const component = mount(WindowAccessLine, { target: document.body, props: { device } });
  await settle();
  const input = document.querySelector("input");
  if (!input) throw new Error("Missing combobox");
  input.focus();
  await tick();
  document.querySelector<HTMLElement>('[role="option"]:last-child')?.click();
  await settle();
  expect(save).toHaveBeenLastCalledWith("computer", ["alpha", "beta"]);
  document.querySelector<HTMLButtonElement>('[aria-label="Remove Alpha"]')?.click();
  await settle();
  expect(save).toHaveBeenLastCalledWith("computer", []);
  save.mockRejectedValueOnce(new Error("denied"));
  document.querySelector<HTMLButtonElement>('[aria-label="Remove Alpha"]')?.click();
  await settle();
  expect(document.querySelector('[data-save-phase="error"]')?.textContent).toContain("denied");
  expect(document.querySelector('[aria-label="Remove Alpha"]')).not.toBeNull();
  await unmount(component);
});
it("Computers settings wires each device and one inheritance hint, refreshing options on pushed lines", async () => {
  vi.useFakeTimers();
  const load = options();
  screenStatus.devices = [device, { ...device, id: "second", name: "Laptop", window_access_lines: [] }];
  const component = mount(ComputersSection, { target: document.body });
  await settle();
  expect(document.querySelectorAll('[role="combobox"]')).toHaveLength(2);
  expect(document.body.textContent.match(/Selected lines and their sublines/g)).toHaveLength(1);
  expect(load).toHaveBeenCalledTimes(2);
  room.conversations = [
    { id: "new", name: "New", topic: "", created_at: 1, archived_at: null, live_count: 1 },
  ];
  await settle();
  expect(load).toHaveBeenCalledTimes(4);
  await unmount(component);
});
it("shows option fetch failures without replacing confirmed selection", async () => {
  vi.useFakeTimers();
  options().mockRejectedValue(new Error("offline"));
  const component = mount(WindowAccessLine, { target: document.body, props: { device } });
  await settle();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("offline");
  expect(document.querySelector('[aria-label="Remove alpha"]')).not.toBeNull();
  await unmount(component);
});
