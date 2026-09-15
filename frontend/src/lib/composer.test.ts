import { describe, expect, it } from "vitest";
import { composerPlaceholder, insertNewline } from "./composer";

describe("composerPlaceholder", () => {
  it("shortens the prompt on the narrow layout", () => {
    expect(composerPlaceholder(true)).toBe("say something…");
  });

  it("keeps the addressing hint on the desktop layout", () => {
    expect(composerPlaceholder(false)).toBe("say something… @name to ring an agent");
  });
});

describe("insertNewline", () => {
  it("inserts a newline at a caret in the middle of text", () => {
    expect(insertNewline("hello world", 5, 5)).toEqual({ value: "hello\n world", caret: 6 });
  });

  it("inserts a newline at the end of text", () => {
    expect(insertNewline("hello", 5, 5)).toEqual({ value: "hello\n", caret: 6 });
  });

  it("replaces a non-empty selection", () => {
    expect(insertNewline("hello world", 5, 11)).toEqual({ value: "hello\n", caret: 6 });
  });

  it("inserts a newline into an empty value", () => {
    expect(insertNewline("", 0, 0)).toEqual({ value: "\n", caret: 1 });
  });
});
