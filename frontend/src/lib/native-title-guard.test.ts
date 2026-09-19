import { describe, expect, it } from "vitest";
import { findNativeTitleAttributes } from "./native-title-guard";

describe("findNativeTitleAttributes", () => {
  it("flags title attributes on native elements, including multiline tags", () => {
    const source = '<button\n  type="button"\n  title="react to this"\n/>';
    expect(findNativeTitleAttributes(source)).toEqual([{ line: 3, tag: "button" }]);
  });

  it("flags expression titles on native elements", () => {
    expect(findNativeTitleAttributes('<span title={names.join(", ")}>')).toEqual([{ line: 1, tag: "span" }]);
  });

  it("allows title props on components", () => {
    expect(findNativeTitleAttributes('<Modal title="save as preset" {close}>')).toEqual([]);
  });

  it("ignores title in scripts, styles, comments, and other attribute names", () => {
    const source = [
      '<script lang="ts">',
      "  let title = $props().title;",
      "</script>",
      '<!-- <button title="nope"> -->',
      '<div data-title="kept" content-title="kept">',
      "  <style>",
      '    /* title="nope" */',
      "  </style>",
      "</div>",
    ].join("\n");
    expect(findNativeTitleAttributes(source)).toEqual([]);
  });

  it("does not end the tag at an arrow function inside an expression", () => {
    expect(findNativeTitleAttributes('<button onclick={() => go(1)} title="flagged">')).toEqual([
      { line: 1, tag: "button" },
    ]);
  });

  it("survives markup that looks like a tag inside an expression", () => {
    expect(findNativeTitleAttributes('<p>{count < 3}</p><button title="flagged">')).toEqual([
      { line: 1, tag: "button" },
    ]);
  });
});
