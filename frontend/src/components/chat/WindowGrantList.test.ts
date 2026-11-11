import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import WindowGrantList from "./WindowGrantList.svelte";
import { screenApi } from "../../lib/screen-api";

const grants = [
  { id: "g1", title: "Editor", holder: "builder", line_name: "Development", conv_id: "dev" },
  { id: "g2", title: "Browser", holder: "designer", line_name: "Design", conv_id: "design" },
];

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

it("names each window's target and revokes only the chosen grant", async () => {
  const revoke = vi.spyOn(screenApi, "revokeWindow").mockResolvedValue({ ok: true });
  const component = mount(WindowGrantList, { target: document.body, props: { grants } });
  expect(document.body.textContent).toContain("Editor → @builder on «Development»");
  expect(document.body.textContent).toContain("Browser → @designer on «Design»");
  document.querySelectorAll("button")[1]?.click();
  await tick();
  expect(revoke).toHaveBeenCalledExactlyOnceWith("g2");
  await unmount(component);
});

it("keeps both grants visible and shows a failed revoke without retrying", async () => {
  const revoke = vi.spyOn(screenApi, "revokeWindow").mockRejectedValue(new Error("Computer disconnected"));
  const component = mount(WindowGrantList, { target: document.body, props: { grants } });
  document.querySelector("button")?.click();
  await tick();
  await tick();
  expect(document.querySelector("[role=alert]")?.textContent).toBe("Computer disconnected");
  expect(document.querySelectorAll("li")).toHaveLength(2);
  expect(revoke).toHaveBeenCalledOnce();
  await unmount(component);
});
