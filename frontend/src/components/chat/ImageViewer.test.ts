import { mount, tick, unmount } from "svelte";
import { describe, expect, it, vi } from "vitest";
import ImageViewer from "./ImageViewer.svelte";
import type { ImageRef } from "../../lib/contracts";

function image(position: number): ImageRef {
  return {
    id: `image-${String(position)}`,
    title: `Signal ${String(position)}`,
    description: `View ${String(position)}`,
    mime: "image/png",
    width: 800,
    height: 560,
    bytes: 100,
    thumb: null,
    slim: { mime: "image/webp", width: 800, height: 560, bytes: 80 },
    urls: {
      original: `/api/media/image-${String(position)}/original`,
      thumb: `/api/media/image-${String(position)}/thumb`,
      slim: `/api/media/image-${String(position)}/slim`,
    },
  };
}

function button(selector: string): HTMLButtonElement {
  const found = document.querySelector(selector);
  if (!(found instanceof HTMLButtonElement)) throw new Error(`missing ${selector}`);
  return found;
}

function expectPosition(title: string, position: string): void {
  expect(document.querySelector(".details h3")?.textContent).toBe(title);
  expect(document.querySelector(".position")?.textContent.trim()).toBe(position);
}

describe("ImageViewer carousel", () => {
  it("renders the slim tier without putting the original token in a link", async () => {
    const viewer = mount(ImageViewer, {
      target: document.body,
      props: { images: [image(1)], initialIndex: 0, close: vi.fn() },
    });
    try {
      expect(document.querySelector(".stage img")?.getAttribute("src")).toBe("/api/media/image-1/slim");
      expect(document.querySelector(".details a")).toBeNull();
      expect(document.querySelector(".download")?.textContent).toContain("download original");
    } finally {
      await unmount(viewer);
    }
  });

  it("lands on adjacent images and wraps in both directions", async () => {
    const viewer = mount(ImageViewer, {
      target: document.body,
      props: { images: [image(1), image(2), image(3)], initialIndex: 1, close: vi.fn() },
    });
    try {
      expectPosition("Signal 2", "2 / 3");

      button(".next").click();
      await tick();
      expectPosition("Signal 3", "3 / 3");

      button(".next").click();
      await tick();
      expectPosition("Signal 1", "1 / 3");

      button(".previous").click();
      await tick();
      expectPosition("Signal 3", "3 / 3");
    } finally {
      await unmount(viewer);
    }
  });
});
