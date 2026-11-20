import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import WindowAccessAudit from "./WindowAccessAudit.svelte";
import { screenApi } from "../lib/screen-api";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

it("loads the current line on demand, pages through its audit and switches lines", async () => {
  const audit = vi
    .spyOn(screenApi, "screenAccessAudit")
    .mockResolvedValueOnce({
      next_before: 10,
      entries: [
        {
          chain_id: "window-grant",
          agent: "worker",
          detail: "window screenshot of «Catalog»",
          time: 1,
          entry_hash: "abc123",
          previous_hash: "def456",
        },
      ],
    })
    .mockResolvedValueOnce({
      next_before: null,
      entries: [
        {
          chain_id: "monitor-share",
          agent: "worker",
          detail: "click left (1,2)",
          time: 1,
          entry_hash: "789abc",
          previous_hash: "",
        },
        {
          chain_id: "window-grant",
          agent: "worker",
          detail: JSON.stringify({
            operation: "screen_window_click",
            grant: "window-grant",
            line: "beta",
            process: "worker",
            route: "cdp",
            point: [100, 100],
            result: "completed",
          }),
          time: 1,
          entry_hash: "012def",
          previous_hash: "",
        },
      ],
    })
    .mockResolvedValueOnce({ next_before: null, entries: [] });
  const component = mount(WindowAccessAudit, {
    target: document.body,
    props: {
      lines: [
        { id: "alpha", name: "Alpha" },
        { id: "beta", name: "Beta" },
      ],
      currentLine: "beta",
    },
  });
  expect(audit).not.toHaveBeenCalled();
  const button = document.querySelector("button");
  if (!button) throw new Error("Missing View log button");
  expect(button.textContent).toContain("View log");
  button.click();
  await tick();
  await tick();
  expect(audit).toHaveBeenLastCalledWith("beta", null);
  expect(document.body.textContent).toContain("window screenshot of «Catalog»");
  expect(document.body.textContent).toContain("window-grant");
  expect(document.body.textContent).toContain("def456");

  const older = Array.from(document.querySelectorAll("button")).find((item) =>
    item.textContent.includes("Load older entries"),
  );
  if (!older) throw new Error("Missing older entries button");
  older.click();
  await tick();
  await tick();
  expect(audit).toHaveBeenLastCalledWith("beta", 10);
  expect(document.body.textContent).toContain("click left (1,2)");
  expect(document.body.textContent).toContain(
    "screen_window_click · route cdp · point [100,100] · result completed",
  );
  expect(document.body.textContent).toContain("Catalog");

  const line = document.querySelector("select");
  if (!line) throw new Error("Missing line picker");
  line.value = "alpha";
  line.dispatchEvent(new Event("change", { bubbles: true }));
  await tick();
  await tick();
  expect(audit).toHaveBeenLastCalledWith("alpha", null);
  expect(document.body.textContent).toContain("No screen access recorded for this line.");
  expect(document.body.textContent).not.toContain("Catalog");
  button.click();
  await tick();
  expect(document.body.textContent).not.toContain("Screen and window access log");
  await unmount(component);
});
