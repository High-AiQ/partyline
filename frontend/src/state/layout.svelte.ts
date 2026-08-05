/**
 * Which region of the app is on screen.
 *
 * On a desktop this store does nothing: all three columns are visible at once
 * and there is nothing to choose between. Below the breakpoint there is not
 * room for three columns — the centre one collapsed to zero width, which meant
 * the conversation itself was invisible on a phone — so the rails become
 * drawers over the line and exactly one of them can be open.
 */

/** The rails, which become overlay drawers on a narrow screen. */
export type DrawerName = "rail" | "board";

/**
 * Where the layout stops being able to show three columns at once.
 *
 * Measured rather than chosen: at 900px the feed is 362px, at 820px it is
 * 282px and already too cramped to read a code block in. This value is also
 * written in `App.svelte`'s media query, and the two have to agree — CSS
 * cannot read a TypeScript constant.
 */
export const NARROW_MAX_WIDTH = 899;
const NARROW_QUERY = `(max-width: ${String(NARROW_MAX_WIDTH)}px)`;

class Layout {
  /** The open drawer, or null when the line has the screen to itself. */
  drawer = $state<DrawerName | null>(null);
  /** True when the viewport cannot hold all three columns. */
  narrow = $state(false);

  get drawerOpen(): boolean {
    return this.drawer !== null;
  }

  open(name: DrawerName): void {
    this.drawer = name;
  }

  close(): void {
    this.drawer = null;
  }

  toggle(name: DrawerName): void {
    this.drawer = this.drawer === name ? null : name;
  }

  /**
   * Track the breakpoint, and return the teardown.
   *
   * Closing the drawer on the way back to desktop is not tidiness: the drawer
   * classes still apply above the breakpoint, and a rail left "open" would
   * come back as a fixed panel floating over a layout that already has room
   * for it.
   */
  watch(): () => void {
    const query = window.matchMedia(NARROW_QUERY);
    const sync = (): void => {
      this.narrow = query.matches;
      if (!this.narrow) this.close();
    };
    sync();
    query.addEventListener("change", sync);
    return () => {
      query.removeEventListener("change", sync);
    };
  }
}

export const layout = new Layout();
