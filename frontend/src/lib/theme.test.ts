import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readStoredTheme, resolveTheme, storeTheme, THEME_STORAGE_KEY } from "./theme";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resolveTheme", () => {
  it("keeps a valid saved choice regardless of the system preference", () => {
    expect(resolveTheme("light", false)).toBe("light");
    expect(resolveTheme("dark", true)).toBe("dark");
  });

  it("falls back to the system preference when nothing valid is saved", () => {
    expect(resolveTheme(null, true)).toBe("light");
    expect(resolveTheme(undefined, false)).toBe("dark");
    expect(resolveTheme("sepia", true)).toBe("light");
    expect(resolveTheme(42, false)).toBe("dark");
  });
});

describe("readStoredTheme", () => {
  it("returns null when nothing is saved", () => {
    expect(readStoredTheme()).toBeNull();
  });

  it("returns the saved theme when it is valid", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(readStoredTheme()).toBe("light");
  });

  it("returns null for an invalid saved value", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredTheme()).toBeNull();
  });

  it("returns null instead of throwing when storage is unreadable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    expect(readStoredTheme()).toBeNull();
  });
});

describe("storeTheme", () => {
  it("saves the theme", () => {
    storeTheme("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("does not throw when storage write fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(() => {
      storeTheme("light");
    }).not.toThrow();
  });
});
