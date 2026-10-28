/** Lazy loader for xterm.js so the emulator stays off the main bundle. */

import type { Terminal } from "@xterm/xterm";

export type XtermTerminal = Terminal;
export type XtermCtor = typeof Terminal;

/** Dynamic import of the package itself — PeekDialog stays on the main chunk. */
export async function loadXterm(): Promise<XtermCtor> {
  const [{ Terminal: Ctor }] = await Promise.all([
    import("@xterm/xterm"),
    import("@xterm/xterm/css/xterm.css"),
  ]);
  return Ctor;
}

/** Tango ANSI colours, adapted to Peek's existing background and foreground. */
export const PEEK_THEME = {
  background: "#0a0c0b",
  foreground: "#c9c4b6",
  cursor: "#c9c4b6",
  cursorAccent: "#0a0c0b",
  selectionBackground: "#54645e",
  selectionForeground: "#ffffff",
  selectionInactiveBackground: "#36413d",
  black: "#2e3436",
  red: "#cc0000",
  green: "#4e9a06",
  yellow: "#c4a000",
  blue: "#3465a4",
  magenta: "#75507b",
  cyan: "#06989a",
  white: "#d3d7cf",
  brightBlack: "#555753",
  brightRed: "#ef2929",
  brightGreen: "#8ae234",
  brightYellow: "#fce94f",
  brightBlue: "#729fcf",
  brightMagenta: "#ad7fa8",
  brightCyan: "#34e2e2",
  brightWhite: "#eeeeec",
};

/** Upgrade an open terminal without delaying its first paint. */
export async function enableWebgl(
  term: Pick<Terminal, "loadAddon">,
  isCurrent: () => boolean,
): Promise<void> {
  try {
    const { WebglAddon } = await import("@xterm/addon-webgl");
    if (!isCurrent()) return;
    const addon = new WebglAddon();
    try {
      addon.onContextLoss(() => {
        addon.dispose();
      });
      term.loadAddon(addon);
    } catch {
      addon.dispose();
    }
  } catch {
    // WebGL and the optional chunk may be unavailable; xterm keeps its default renderer.
  }
}
