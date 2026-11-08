import { tick } from "svelte";

/** The items a popup menu moves between: plain actions and checkable toggles. */
const ITEM_SELECTOR = '[role="menuitem"], [role="menuitemcheckbox"]';

/**
 * The keyboard, pointer and focus rules shared by the composer's popup menus.
 *
 * A component keeps its own markup and binds `container`, `anchor` and `menu`
 * to its elements. This owns the open state, arrow keys, Escape, outside taps
 * and the return of focus to the button that opened the menu. Arrow keys and
 * Escape are handled on the window, so the components wire `keydown` and
 * `pointerdown` onto `<svelte:window>`.
 */
export class PopupMenu {
  open = $state(false);
  container = $state.raw<HTMLElement | null>(null);
  anchor = $state.raw<HTMLElement | null>(null);
  menu = $state.raw<HTMLElement | null>(null);

  #items(): HTMLElement[] {
    return [...(this.menu?.querySelectorAll<HTMLElement>(ITEM_SELECTOR) ?? [])];
  }

  close = (): void => {
    this.open = false;
    this.anchor?.focus();
  };

  show = async (): Promise<void> => {
    this.open = true;
    await tick();
    this.#items()[0]?.focus();
  };

  /** Close without moving focus: for an item whose action moves focus itself. */
  dismiss = (): void => {
    this.open = false;
  };

  toggle = (): void => {
    if (this.open) this.close();
    else void this.show();
  };

  keydown = (event: KeyboardEvent): void => {
    if (!this.open) {
      if (document.activeElement === this.anchor && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault();
        void this.show();
      }
      return;
    }
    if (event.key === "Tab") {
      this.open = false;
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.close();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const items = this.#items();
      const index = items.indexOf(document.activeElement as HTMLElement);
      items[(index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
    }
  };

  pointerdown = (event: PointerEvent): void => {
    if (this.open && event.target instanceof Node && !this.container?.contains(event.target)) this.close();
  };
}
