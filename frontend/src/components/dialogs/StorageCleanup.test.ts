import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import StorageCleanup from "./StorageCleanup.svelte";
import { storageCleanupApi } from "../../lib/storage-api";

async function settle(): Promise<void> {
  for (let turn = 0; turn < 6; turn += 1) await tick();
}

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

it("cleans in one click and reports kept paths, reasons and idle lines", async () => {
  vi.spyOn(storageCleanupApi, "details").mockResolvedValue({
    kept: [{ path: "/repo/clone", reason: "independent nested repository", size_bytes: 2000 }],
    idle_lines: [{ id: "idle", name: "Old work", idle_since: 0, size_bytes: 5000 }],
  });
  const clean = vi.spyOn(storageCleanupApi, "cleanup").mockResolvedValue({
    removed: ["cache"],
    freed_bytes: 3000,
    skipped: [{ path: "/repo/clone", reason: "independent nested repository", size_bytes: 2000 }],
  });
  const refreshed = vi.fn();
  const component = mount(StorageCleanup, { target: document.body, props: { refreshed } });
  try {
    await settle();
    expect(document.body.textContent).toContain("On by default");
    expect(document.body.textContent).toContain("Old work · 5.0 KB");
    document.querySelector("button")?.click();
    await settle();
    expect(clean).toHaveBeenCalledTimes(1);
    expect(refreshed).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain("Freed 3.0 KB");
    expect(document.body.textContent).toContain("/repo/clone · 2.0 KB — independent nested repository");
  } finally {
    await unmount(component);
  }
});

it("renders duplicate kept paths from aliased roots", async () => {
  const duplicate = { path: "/repo/same", reason: "kept for recovery", size_bytes: 1000 };
  vi.spyOn(storageCleanupApi, "details").mockResolvedValue({
    kept: [duplicate, duplicate],
    idle_lines: [],
  });
  vi.spyOn(storageCleanupApi, "cleanup").mockResolvedValue({
    removed: [],
    freed_bytes: 0,
    skipped: [duplicate, duplicate],
  });
  const component = mount(StorageCleanup, { target: document.body, props: { refreshed: vi.fn() } });
  try {
    await settle();
    expect(document.querySelectorAll("li")).toHaveLength(2);
    document.querySelector("button")?.click();
    await settle();
    expect(document.querySelectorAll("li")).toHaveLength(4);
    expect(document.body.textContent).toContain("Kept 2 items");
  } finally {
    await unmount(component);
  }
});
