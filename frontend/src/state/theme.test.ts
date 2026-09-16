import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY } from "../lib/theme.js";
import { ThemeStore } from "./theme.svelte.js";

function mockMatchMedia(prefersLight: boolean): {
  fireChange: (matches: boolean) => void;
} {
  const listeners = new Set<EventListenerOrEventListenerObject>();
  let matches = prefersLight;
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        get matches() {
          return matches;
        },
        media: query,
        onchange: null,
        addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
          listeners.add(listener);
        },
        removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
          listeners.delete(listener);
        },
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as MediaQueryList,
  );
  return {
    fireChange: (next: boolean) => {
      matches = next;
      const event = Object.assign(new Event("change"), { matches: next });
      for (const listener of listeners) {
        if (typeof listener === "function") listener(event);
        else listener.handleEvent(event);
      }
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ThemeStore", () => {
  it("follows the system preference when nothing is saved", () => {
    mockMatchMedia(true);
    expect(new ThemeStore().current).toBe("light");

    mockMatchMedia(false);
    expect(new ThemeStore().current).toBe("dark");
  });

  it("keeps a saved choice across reload regardless of the system preference", () => {
    mockMatchMedia(true);
    new ThemeStore().set("dark");

    mockMatchMedia(true);
    const restored = new ThemeStore();
    expect(restored.current).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("falls back to the system preference for an invalid saved value", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    mockMatchMedia(true);
    expect(new ThemeStore().current).toBe("light");
  });

  it("toggle flips and persists the explicit choice", () => {
    mockMatchMedia(false);
    const store = new ThemeStore();
    expect(store.current).toBe("dark");

    store.toggle();
    expect(store.current).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");

    store.toggle();
    expect(store.current).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("follows live system changes only while unset", () => {
    const media = mockMatchMedia(false);
    const store = new ThemeStore();
    const stop = store.watch();
    expect(store.current).toBe("dark");

    media.fireChange(true);
    expect(store.current).toBe("light");

    store.set("dark");
    media.fireChange(true);
    expect(store.current).toBe("dark");

    stop();
  });

  it("watch is a no-op teardown when matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);
    const store = new ThemeStore();
    expect(() => {
      store.watch()();
    }).not.toThrow();
    vi.unstubAllGlobals();
  });
});
