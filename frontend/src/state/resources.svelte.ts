/** Fleet resource snapshots arrive on connect and whenever the server publishes a change. */
import type { ResourceSnapshot } from "../lib/resource-api";

class Resources {
  snapshot = $state<ResourceSnapshot | null>(null);
  popoverOpen = $state(false);
}

export const resources = new Resources();
