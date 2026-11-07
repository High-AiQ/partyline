import { describe, expect, it } from "vitest";
import { SECTIONS, SETTINGS, countBySection, searchSettings, sectionInfo } from "./settings-registry";
import { SECTION_IDS } from "./settings-route";

describe("settings registry", () => {
  it("has one nav entry per route and only settings that belong to a section", () => {
    expect(SECTIONS.map((section) => section.id)).toEqual([...SECTION_IDS]);
    expect(new Set(SETTINGS.map((setting) => setting.id)).size).toBe(SETTINGS.length);
    for (const setting of SETTINGS) {
      expect(SECTION_IDS).toContain(setting.section);
      expect(setting.id.startsWith("setting-")).toBe(true);
    }
    expect(sectionInfo("voice").label).toBe("Voice");
  });

  it("matches every word against label, description, keywords and section, ignoring case", () => {
    expect(searchSettings("   ")).toEqual([]);
    expect(searchSettings("THEME").map((s) => s.id)).toEqual(["setting-theme"]);
    // "dark" is only a keyword; a multi-word query needs every word in one setting.
    expect(searchSettings("dark").map((s) => s.id)).toContain("setting-theme");
    expect(searchSettings("early memory warning").map((s) => s.id)).toEqual(["setting-memory-warning"]);
    // A description word finds the row, and a section name finds all of its rows.
    expect(searchSettings("archive").map((s) => s.id)).toEqual(["setting-task-history"]);
    expect(searchSettings("about").map((s) => s.id)).toContain("setting-version");
    expect(searchSettings("no such setting anywhere")).toEqual([]);
  });

  it("counts results per section for the nav badges", () => {
    const counts = countBySection(searchSettings("memory"));
    expect(counts.get("resources")).toBeGreaterThan(3);
    expect(counts.get("voice")).toBeUndefined();
  });
});
