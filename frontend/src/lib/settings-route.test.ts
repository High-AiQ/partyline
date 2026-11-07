import { describe, expect, it } from "vitest";
import { SECTION_IDS, isSettingsRoute, parseSettingsRoute, settingsRoute } from "./settings-route";

describe("settings routes", () => {
  it("round trips every section through its deep link", () => {
    for (const id of SECTION_IDS) expect(parseSettingsRoute(settingsRoute(id))).toBe(id);
    expect(settingsRoute("voice")).toBe("#/settings/voice");
  });

  it("opens the first tab for bare or unknown settings links, and ignores everything else", () => {
    expect(parseSettingsRoute("#/settings")).toBe("general");
    expect(parseSettingsRoute("#/settings/")).toBe("general");
    expect(parseSettingsRoute("#/settings/nope")).toBe("general");
    expect(parseSettingsRoute("#/c/abc")).toBeNull();
    expect(parseSettingsRoute("")).toBeNull();
    expect(parseSettingsRoute("#/settings/voice/extra")).toBeNull();
    expect(isSettingsRoute("#/settings/about")).toBe(true);
    expect(isSettingsRoute("#/c/settings")).toBe(false);
  });
});
