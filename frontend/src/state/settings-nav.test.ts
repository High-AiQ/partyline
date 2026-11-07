import { afterEach, describe, expect, it } from "vitest";
import { settingsNav } from "./settings-nav.svelte.js";

afterEach(() => {
  settingsNav.close();
  history.replaceState({}, "", "/");
});

describe("settings navigation", () => {
  it("opens on a tab, remembers the line it covered, and returns there on close", () => {
    history.replaceState({}, "", "/#/c/line-1");
    settingsNav.show("voice", "setting-asr-add");
    expect(location.hash).toBe("#/settings/voice");
    expect(settingsNav.section).toBe("voice");
    expect(settingsNav.focusTarget).toBe("setting-asr-add");
    settingsNav.show("about");
    expect(location.hash).toBe("#/settings/about");
    settingsNav.close();
    expect(settingsNav.section).toBeNull();
    expect(location.hash).toBe("#/c/line-1");
  });

  it("follows the URL on Back and Forward, and closing after leaving changes nothing", () => {
    history.replaceState({}, "", "/#/settings/storage");
    settingsNav.sync();
    expect(settingsNav.section).toBe("storage");
    history.replaceState({}, "", "/#/settings/bogus");
    settingsNav.sync();
    expect(settingsNav.section).toBe("general");
    history.replaceState({}, "", "/#/c/line-2");
    settingsNav.sync();
    expect(settingsNav.section).toBeNull();
    settingsNav.close();
    expect(location.hash).toBe("#/c/line-2");
  });

  it("opened from a deep link, closing leaves no settings route behind", () => {
    history.replaceState({}, "", "/#/settings/voice");
    settingsNav.sync();
    settingsNav.show("general");
    settingsNav.close();
    expect(location.hash).toBe("");
  });
});
