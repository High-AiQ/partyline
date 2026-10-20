import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import StorageSection from "./StorageSection.svelte";
import StorageClearDialog from "./StorageClearDialog.svelte";
import { storageApi, type StorageCategory } from "../../lib/storage-api";
import { dialogs } from "../../state/dialogs.svelte";

const review: StorageCategory = {
  key: "review",
  label: "Review checkouts",
  paths: ["/repo/.review"],
  bytes: 5000,
  clearable: true,
  clearable_bytes: 3000,
  clearable_count: 7,
  candidates: ["/repo/.review/aaa", "/repo/.review/bbb"],
  approximate: false,
};
const media: StorageCategory = { ...review, key: "media", label: "Media", clearable: false };

async function settle(): Promise<void> {
  for (let turn = 0; turn < 5; turn += 1) await tick();
}

afterEach(() => {
  vi.restoreAllMocks();
  dialogs.closeAll();
  document.body.replaceChildren();
});

describe("StorageSection", () => {
  it("lists sizes and opens a confirmation instead of clearing", async () => {
    vi.spyOn(storageApi, "list").mockResolvedValue([review, media]);
    const clear = vi.spyOn(storageApi, "clear");
    const section = mount(StorageSection, { target: document.body });
    try {
      await settle();
      expect(document.querySelector('[data-storage="review"]')?.textContent).toContain(
        "clearable 3.0 KB (7)",
      );
      expect(document.querySelector('[data-storage="media"] button')).toBeNull();
      const button = document.querySelector('[data-storage="review"] button');
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing clear button");
      button.click();
      await settle();
      expect(dialogs.stack[0]?.component).toBe(StorageClearDialog);
      expect(clear).not.toHaveBeenCalled();
    } finally {
      await unmount(section);
    }
  });
});

describe("StorageClearDialog", () => {
  it("lists what will be removed and clears only after confirming", async () => {
    const clear = vi
      .spyOn(storageApi, "clear")
      .mockResolvedValue({ removed: ["a"], freed_bytes: 3000, skipped: [] });
    const cleared = vi.fn();
    const close = vi.fn();
    const dialog = mount(StorageClearDialog, {
      target: document.body,
      props: { category: review, cleared, close },
    });
    try {
      await settle();
      expect(document.body.textContent).toContain("Removes 7 items");
      expect(document.body.textContent).toContain("/repo/.review/aaa");
      expect(document.body.textContent).toContain("and 5 more");
      expect(clear).not.toHaveBeenCalled();
      const confirm = [...document.querySelectorAll("button")].find((item) => item.type === "submit");
      if (!confirm) throw new Error("missing confirm button");
      confirm.click();
      await settle();
      expect(clear).toHaveBeenCalledWith("review", null);
      expect(close).toHaveBeenCalled();
      expect(cleared).toHaveBeenCalled();
    } finally {
      await unmount(dialog);
    }
  });
});
