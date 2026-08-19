/** Room-scoped activity state and its REST/WebSocket reconciliation. */

import { PresenceSnapshotSync } from "../lib/presence-sync.js";
import { presence } from "./presence.svelte.js";

export const presenceSync = new PresenceSnapshotSync(presence);
