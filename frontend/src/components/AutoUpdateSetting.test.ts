import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import AutoUpdateSetting from "./AutoUpdateSetting.svelte";
import { screenApi } from "../lib/screen-api";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});
it("defaults off, saves the person's choice and restores the confirmed value on failure", async () => {
  const save = vi.spyOn(screenApi, "autoUpdate").mockResolvedValue({ ok: true });
  const component = mount(AutoUpdateSetting, {
    target: document.body,
    props: { device: { id: "computer", name: "Desk", os: "Windows", online: false, monitors: [] } },
  });
  await tick();
  const input = document.querySelector("input");
  if (!input) throw new Error("Missing auto update toggle");
  expect(input.checked).toBe(false);
  input.click();
  await tick();
  await tick();
  expect(save).toHaveBeenCalledWith("computer", true);
  save.mockRejectedValueOnce(new Error("unavailable"));
  input.checked = false;
  input.click();
  await tick();
  await tick();
  expect(input.checked).toBe(false);
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("Could not save");
  await unmount(component);
});
