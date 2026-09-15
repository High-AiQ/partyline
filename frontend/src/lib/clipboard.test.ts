import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

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

afterEach(() => {
  setClipboard(undefined);
  delete (document as { execCommand?: unknown }).execCommand;
  vi.restoreAllMocks();
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
