import { beforeEach, describe, expect, it, vi } from "vitest";
import { enableWebgl, PEEK_THEME } from "./xterm";

const mocks = vi.hoisted(() => ({
  dispose: vi.fn(),
  onContextLoss: vi.fn(),
  construct: vi.fn(),
}));
vi.mock("@xterm/addon-webgl", () => ({
  WebglAddon: class {
    dispose = mocks.dispose;
    onContextLoss = mocks.onContextLoss;
    constructor() {
      mocks.construct();
    }
  },
}));

const ansi = [
  "black",
  "red",
  "green",
  "yellow",
  "blue",
  "magenta",
  "cyan",
  "white",
  "brightBlack",
  "brightRed",
  "brightGreen",
  "brightYellow",
  "brightBlue",
  "brightMagenta",
  "brightCyan",
  "brightWhite",
] as const;

describe("Peek terminal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("defines all sixteen distinct ANSI colours and terminal colours", () => {
    const colours = ansi.map((key) => PEEK_THEME[key]);
    expect(colours.every((colour) => /^#[0-9a-f]{6}$/i.test(colour))).toBe(true);
    expect(new Set(colours).size).toBe(16);
    for (const key of [
      "background",
      "foreground",
      "cursor",
      "cursorAccent",
      "selectionBackground",
      "selectionForeground",
      "selectionInactiveBackground",
    ] as const) {
      expect(PEEK_THEME[key]).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("disposes on context loss", async () => {
    const loadAddon = vi.fn();
    const term = { loadAddon };
    await enableWebgl(term, () => true);
    expect(loadAddon).toHaveBeenCalledOnce();
    const callback = mocks.onContextLoss.mock.calls[0]?.[0] as (() => void) | undefined;
    expect(callback).toBeDefined();
    callback?.();
    expect(mocks.dispose).toHaveBeenCalledOnce();
  });

  it("silently falls back when construction or activation fails", async () => {
    const term = {
      loadAddon: vi.fn(() => {
        throw new Error("no WebGL");
      }),
    };
    await expect(enableWebgl(term, () => true)).resolves.toBeUndefined();
    expect(mocks.dispose).toHaveBeenCalledOnce();
    mocks.construct.mockImplementationOnce(() => {
      throw new Error("unavailable");
    });
    await expect(enableWebgl(term, () => true)).resolves.toBeUndefined();
  });

  it("does not attach to a terminal closed while loading", async () => {
    const loadAddon = vi.fn();
    const term = { loadAddon };
    await enableWebgl(term, () => false);
    expect(mocks.construct).not.toHaveBeenCalled();
    expect(loadAddon).not.toHaveBeenCalled();
  });
  it("silently falls back if the addon chunk cannot load", async () => {
    vi.resetModules();
    vi.doMock("@xterm/addon-webgl", () => {
      throw new Error("chunk unavailable");
    });
    try {
      const { enableWebgl: load } = await import("./xterm");
      const loadAddon = vi.fn();
      await expect(load({ loadAddon }, () => true)).resolves.toBeUndefined();
      expect(loadAddon).not.toHaveBeenCalled();
    } finally {
      vi.doUnmock("@xterm/addon-webgl");
    }
  });
});
