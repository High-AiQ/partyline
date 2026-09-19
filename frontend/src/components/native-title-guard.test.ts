import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findNativeTitleAttributes } from "../lib/native-title-guard";

function componentFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = `${directory}/${entry.name}`;
    return entry.isDirectory() ? componentFiles(path) : path;
  });
}

describe("native tooltip guard", () => {
  it("bans DOM title attributes across every component under src/components", () => {
    const root = join(process.cwd(), "src", "components");
    const violations = componentFiles(root)
      .filter((path) => path.endsWith(".svelte"))
      .flatMap((path) =>
        findNativeTitleAttributes(readFileSync(path, "utf8")).map(
          (violation) => `${path}:${String(violation.line)} <${violation.tag}>`,
        ),
      );
    expect(violations).toEqual([]);
  });
});
