/**
 * The dialog stack.
 *
 * Dialogs are opened from all over the app — a row menu, the board, the
 * operator strip — and none of those places is a sensible parent for a
 * viewport-covering overlay. They push a component here instead, and `App`
 * renders the stack at the top level where the overlay belongs.
 */

let nextKey = 0;

class Dialogs {
  stack = $state([]);

  /**
   * @param component a Svelte component taking a `close` prop
   * @param props     everything else the dialog needs
   */
  open(component, props = {}) {
    const entry = { key: ++nextKey, component, props };
    this.stack.push(entry);
    return () => this.close(entry.key);
  }

  close(key) {
    this.stack = this.stack.filter((entry) => entry.key !== key);
  }

  /** Escape closes the topmost dialog only, as a stack should. */
  closeTop() {
    this.stack.pop();
  }
}

export const dialogs = new Dialogs();
