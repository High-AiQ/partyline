import { describe, expect, it } from "vitest";
import { insertNewline } from "./composer";

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
