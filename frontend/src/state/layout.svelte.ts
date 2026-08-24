/** Which side regions are visible as columns or narrow-screen drawers. */

import { z } from "zod";

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
const DESKTOP_COLUMNS_KEY = "partyline_desktop_columns";

export const DesktopColumnsSchema = z.object({
  railCollapsed: z.boolean(),
  boardCollapsed: z.boolean(),
});
export type DesktopColumns = z.infer<typeof DesktopColumnsSchema>;

const DEFAULT_DESKTOP_COLUMNS: DesktopColumns = {
  railCollapsed: false,
  boardCollapsed: false,
};

function readDesktopColumns(): DesktopColumns {
  try {
    const raw = localStorage.getItem(DESKTOP_COLUMNS_KEY);
    if (raw === null) return DEFAULT_DESKTOP_COLUMNS;
    const parsed = DesktopColumnsSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : DEFAULT_DESKTOP_COLUMNS;
  } catch {
    return DEFAULT_DESKTOP_COLUMNS;
  }
}

function storeDesktopColumns(columns: DesktopColumns): void {
  try {
    localStorage.setItem(DESKTOP_COLUMNS_KEY, JSON.stringify(columns));
  } catch {
    // A blocked or full storage area should not make the controls stop working.
  }
}

export class Layout {
  /** The open drawer, or null when the line has the screen to itself. */
  drawer = $state<DrawerName | null>(null);
  /** True when the viewport cannot hold all three columns. */
  narrow = $state(false);
  railCollapsed = $state(false);
  boardCollapsed = $state(false);

  constructor() {
    const saved = readDesktopColumns();
    this.railCollapsed = saved.railCollapsed;
    this.boardCollapsed = saved.boardCollapsed;
  }

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

  toggleColumn(name: DrawerName): void {
    if (name === "rail") this.railCollapsed = !this.railCollapsed;
    else this.boardCollapsed = !this.boardCollapsed;
    storeDesktopColumns({
      railCollapsed: this.railCollapsed,
      boardCollapsed: this.boardCollapsed,
    });
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
