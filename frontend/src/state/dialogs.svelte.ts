/**
 * The dialog stack.
 *
 * Dialogs are opened from all over the app — a row menu, the board, the
 * operator strip — and none of those places is a sensible parent for a
 * viewport-covering overlay. They push a component here instead, and `App`
 * renders the stack at the top level where the overlay belongs.
 */

import type { Component } from "svelte";

let nextKey = 0;

export type DialogProperties = Record<string, unknown>;

export interface DialogCloseProperties {
  close: () => void;
}

export type DialogInput<Props extends DialogCloseProperties> = Omit<Props, "close">;

export interface DialogEntry {
  key: number;
  // A heterogeneous stack erases each component's concrete props only after
  // `open` has checked them. `Component` is Svelte's named existential type.
  component: Component;
  props: DialogProperties;
}

class Dialogs {
  stack = $state<DialogEntry[]>([]);

  /**
   * @param component a Svelte component taking a `close` prop
   * @param props     everything else the dialog needs
   */
  open(component: Component<DialogCloseProperties>): () => void;
  open<Props extends DialogCloseProperties>(
    component: Component<Props>,
    props: DialogInput<Props>,
  ): () => void;
  open(component: Component, props: DialogProperties = {}): () => void {
    const entry = { key: ++nextKey, component, props };
    this.stack.push(entry);
    return () => {
      this.close(entry.key);
    };
  }

  close(key: number): void {
    this.stack = this.stack.filter((entry) => entry.key !== key);
  }

  /** Escape closes the topmost dialog only, as a stack should. */
  closeTop(): void {
    this.stack.pop();
  }
}

export const dialogs = new Dialogs();
