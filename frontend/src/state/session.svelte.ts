/**
 * The operator, and the things that belong to the server rather than to a line:
 * the adapter registry, saved presets, and the version badge.
 */

import { api } from "../lib/api";
import type { Adapter, Preset } from "../lib/contracts";
import { normalizeHandle, isReserved, readHandle, readOrMintClientId, writeHandle } from "../lib/identity";

class Session {
  handle = $state(readHandle());
  clientId = readOrMintClientId();
  version = $state<string | null>(null);
  instanceName = $state<string | null>(null);

  adapters = $state<Adapter[]>([]);
  presets = $state<Preset[]>([]);

  /** Set when the server refuses the handle, so the gate can say why. */
  gateError = $state("");
  gateOpen = $state(!readHandle());

  get signedIn(): boolean {
    return Boolean(this.handle) && !this.gateOpen;
  }

  openGate(message = ""): void {
    this.gateError = message;
    this.gateOpen = true;
  }

  /**
   * Take a handle from the gate. Returns an error string, or null on success —
   * the caller decides how to show it, this decides whether it is allowed.
   */
  signIn(raw: string): string | null {
    const handle = normalizeHandle(raw);
    if (!handle) return "pick a handle";
    if (isReserved(handle)) return "that handle is reserved";

    this.handle = writeHandle(handle);
    this.gateError = "";
    this.gateOpen = false;
    return null;
  }

  async loadVersion(): Promise<void> {
    try {
      const identity = await api.version();
      this.version = identity.version;
      this.instanceName = identity.instance_name;
    } catch {
      /* the badge is decoration; a server too sick to answer will say so elsewhere */
    }
  }

  /** The release the socket just told us it is. Required on every hello, so
   *  there is no "leave whatever the badge already said" branch — keeping one
   *  is how the badge stayed on `v0.21.1` against a `v0.21.3` server. */
  acceptServerVersion(version: string): void {
    this.version = version;
  }

  /** Everything a handshake makes stale. The adapter list follows the same
   *  rule as the version badge: every handshake may follow a server whose
   *  adapters changed — an import, a reload, a restart onto a new release —
   *  and a Python-only release deliberately reloads no tab, so mount-time
   *  state would otherwise be the only state a document ever has. A picker
   *  omitting an adapter the server had offered for an hour was this
   *  staleness, observed live. */
  acceptHandshake(version: string, instanceName: string | null): void {
    this.acceptServerVersion(version);
    this.instanceName = instanceName;
    void this.loadAdapters();
  }

  async loadAdapters(): Promise<void> {
    try {
      this.adapters = await api.adapters();
    } catch {
      this.adapters = [];
    }
  }

  async loadPresets(): Promise<void> {
    try {
      this.presets = await api.presets();
    } catch {
      this.presets = [];
    }
  }
}

export const session = new Session();
