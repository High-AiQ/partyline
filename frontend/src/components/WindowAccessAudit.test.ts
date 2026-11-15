import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import WindowAccessAudit from "./WindowAccessAudit.svelte";
import { screenApi } from "../lib/screen-api";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

it("loads the selected line's newest audit entries on demand and hides them", async () => {
  const audit = vi.spyOn(screenApi, "windowAccessAudit").mockResolvedValue({
    chain_head: "abc123",
    entries: [
      {
        agent: "worker",
        call: "uia_read",
        app: "editor.exe",
        title: "Catalog",
        result: "read",
        time: 1,
        entry_hash: "abc123",
      },
    ],
  });
  const component = mount(WindowAccessAudit, {
    target: document.body,
    props: {
      device: {
        id: "computer",
        name: "Desk",
        os: "test",
        online: true,
        monitors: [],
        window_access_line: "alpha",
      },
    },
  });
  expect(audit).not.toHaveBeenCalled();
  const button = document.querySelector("button");
  if (!button) throw new Error("Missing View log button");
  expect(button.textContent).toContain("View log");
  button.click();
  await tick();
  await tick();
  expect(audit).toHaveBeenCalledWith("alpha");
  expect(document.body.textContent).toContain("uia_read");
  expect(document.body.textContent).toContain("Catalog");
  expect(document.body.textContent).toContain("Chain head: abc123");
  button.click();
  await tick();
  expect(document.body.textContent).not.toContain("uia_read");
  await unmount(component);
});
