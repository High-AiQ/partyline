/** Fleet resource snapshot shared by the top bar and incoming wire events. */
import { getResources, type ResourceSnapshot } from "../lib/resource-api";

class Resources {
  snapshot = $state<ResourceSnapshot | null>(null);
  popoverOpen = $state(false);
  #refreshTimer: ReturnType<typeof setTimeout> | null = null;

  async load(): Promise<void> {
    try {
      this.snapshot = await getResources();
    } catch {
      // The indicator remains quiet while offline; reconnect events refresh it.
    }
  }

  scheduleRefresh(): void {
    if (this.#refreshTimer !== null) clearTimeout(this.#refreshTimer);
    this.#refreshTimer = setTimeout(() => {
      this.#refreshTimer = null;
      void this.load();
    }, 300);
  }
}

export const resources = new Resources();
