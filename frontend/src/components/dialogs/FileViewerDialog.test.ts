import { mount, tick, unmount } from "svelte";
import { describe, expect, it, vi } from "vitest";
import FileViewerDialog from "./FileViewerDialog.svelte";
import type { FileRef } from "../../lib/contracts";
import * as http from "../../lib/http";
import { renderFileMarkdown } from "../../lib/markdown";
import { viewableFileType, VIEW_MAX_BYTES } from "../../lib/files";

const file: FileRef = {
  id: "file",
  kind: "file",
  filename: "notes.txt",
  title: null,
  description: null,
  mime: "text/plain",
  bytes: 5,
  width: null,
  height: null,
  thumb: null,
  slim: null,
  urls: { original: "/api/media/file/original", thumb: "/api/media/file/original", slim: null },
};

describe("file viewer", () => {
  it("recognizes only supported extensions", () => {
    expect(viewableFileType(file)).toBe("txt");
    expect(viewableFileType({ ...file, filename: "README.MD" })).toBe("md");
    expect(viewableFileType({ ...file, filename: "notes.pdf" })).toBeNull();
  });
  it("renders Markdown blocks and safe links and images without HTML injection", () => {
    const host = document.createElement("div");
    host.innerHTML = renderFileMarkdown(
      "# Heading\n\n- item\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n```js\ncode\n```\n\n[link](https://example.com) ![image](https://example.com/a.png)\n\n<script>alert(1)</script> [bad](javascript:alert(1))",
    );
    expect(host.querySelector(".md-h1")?.textContent).toBe("Heading");
    expect(host.querySelector("li")?.textContent).toBe("item");
    expect(host.querySelector("table")).not.toBeNull();
    expect(host.querySelector("pre code")?.textContent).toContain("code");
    expect(host.querySelector("a")?.getAttribute("rel")).toContain("noopener");
    expect(host.querySelector("a")?.getAttribute("target")).toBe("_blank");
    expect(host.querySelector("img")?.getAttribute("src")).toBe("https://example.com/a.png");
    expect(host.querySelector("script")).toBeNull();
    expect(host.querySelector('[href^="javascript:"]')).toBeNull();
  });
  it("loads text through the bounded file transport and preserves whitespace", async () => {
    const blob = new Blob();
    Object.defineProperty(blob, "text", { value: () => Promise.resolve("first\n  second") });
    const request = vi.spyOn(http, "requestBlob").mockResolvedValue(blob);
    const viewer = mount(FileViewerDialog, { target: document.body, props: { file, close: vi.fn() } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("pre")?.textContent).toBe("first\n  second");
      });
      expect(request).toHaveBeenCalledWith(file.urls.original, true, VIEW_MAX_BYTES);
    } finally {
      await unmount(viewer);
      request.mockRestore();
    }
  });
  it("shows oversized files with a download option without fetching", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const viewer = mount(FileViewerDialog, {
      target: document.body,
      props: { file: { ...file, bytes: VIEW_MAX_BYTES + 1 }, close: vi.fn() },
    });
    try {
      await tick();
      expect(document.body.textContent).toContain("1 MiB viewing limit");
      expect(document.body.textContent).toContain("Download file");
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      await unmount(viewer);
      fetchSpy.mockRestore();
    }
  });
});
