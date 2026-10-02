import { afterEach, describe, expect, it, vi } from "vitest";
import { copyRichText, copyText } from "./clipboard";

function setClipboard(clipboard: unknown): void {
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
}

function stubExecCommand(implementation: () => boolean): ReturnType<typeof vi.fn> {
  const exec = vi.fn(implementation);
  Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
  return exec;
}

function captureTextareaSelects(): string[] {
  const selections: string[] = [];
  vi.spyOn(HTMLTextAreaElement.prototype, "select").mockImplementation(function (this: HTMLTextAreaElement) {
    selections.push(this.value);
  });
  return selections;
}

function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("clipboard blob was not text"));
    });
    reader.addEventListener("error", () => {
      reject(new Error("could not read clipboard blob"));
    });
    reader.readAsText(blob);
  });
}

afterEach(() => {
  setClipboard(undefined);
  delete (document as { execCommand?: unknown }).execCommand;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("copyText", () => {
  it("writes through the async clipboard when the origin allows it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const exec = stubExecCommand(() => false);
    await expect(copyText("hello")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(exec).not.toHaveBeenCalled();
  });

  it("falls back to a textarea and execCommand without the async clipboard", async () => {
    setClipboard(undefined);
    const exec = stubExecCommand(() => true);
    const selections = captureTextareaSelects();
    await expect(copyText("**markdown**\nstays raw")).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
    expect(selections).toEqual(["**markdown**\nstays raw"]);
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("still lands the text when the async clipboard rejects", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });
    const exec = stubExecCommand(() => true);
    await expect(copyText("hello")).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("reports failure when every path fails", async () => {
    setClipboard(undefined);
    stubExecCommand(() => false);
    await expect(copyText("hello")).resolves.toBe(false);
  });
});

describe("copyRichText", () => {
  it("writes html and plain text through ClipboardItem on a secure origin", async () => {
    class TestClipboardItem {
      constructor(readonly values: Record<string, Blob>) {}
    }
    vi.stubGlobal("ClipboardItem", TestClipboardItem);
    let copiedItem: TestClipboardItem | undefined;
    const write = vi.fn((items: ClipboardItem[]): Promise<void> => {
      copiedItem = items[0] as unknown as TestClipboardItem;
      return Promise.resolve();
    });
    setClipboard({ write });
    await expect(copyRichText({ html: "<b>hi</b>", text: "hi" })).resolves.toBe(true);
    const item = copiedItem;
    if (!item) throw new Error("clipboard item missing");
    const html = item.values["text/html"];
    const text = item.values["text/plain"];
    if (!html || !text) throw new Error("clipboard formats missing");
    expect(await blobText(html)).toBe("<b>hi</b>");
    expect(await blobText(text)).toBe("hi");
  });

  it("selects a hidden rendered node and uses execCommand over plain http", async () => {
    setClipboard(undefined);
    const exec = stubExecCommand(() => {
      expect(document.querySelector("[aria-hidden='true']")?.innerHTML).toBe("<p><b>rich</b></p>");
      expect(window.getSelection()?.toString()).toBe("rich");
      return true;
    });
    await expect(copyRichText({ html: "<p><b>rich</b></p>", text: "rich" })).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
    expect(document.querySelector("[aria-hidden='true']")).toBeNull();
  });

  it("reports failure when secure and selection-based rich copies fail", async () => {
    setClipboard(undefined);
    stubExecCommand(() => false);
    await expect(copyRichText({ html: "<p>rich</p>", text: "rich" })).resolves.toBe(false);
  });
});
