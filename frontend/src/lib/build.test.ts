import { describe, expect, it } from "vitest";
import { buildChanged } from "./build";

describe("buildChanged", () => {
  it("detects a server serving a different frontend", () => {
    expect(buildChanged("old", "new")).toBe(true);
  });

  it("keeps an ordinary reconnect on the current page", () => {
    expect(buildChanged("same", "same")).toBe(false);
  });

  it("does not loop against dev or an older server without a build id", () => {
    expect(buildChanged("", "server")).toBe(false);
    expect(buildChanged("client", "")).toBe(false);
  });
});
