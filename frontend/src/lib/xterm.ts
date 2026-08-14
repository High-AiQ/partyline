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
