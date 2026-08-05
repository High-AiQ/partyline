/**
 * The operator, and the things that belong to the server rather than to a line:
 * the adapter registry, saved presets, and the version badge.
 */

import { api } from "../lib/api.js";
import { normalizeHandle, isReserved, readHandle, readOrMintClientId, writeHandle } from "../lib/identity.js";

class Session {
  handle = $state(readHandle());
  clientId = readOrMintClientId();
  version = $state(null);

  adapters = $state([]);
  presets = $state([]);

  /** Set when the server refuses the handle, so the gate can say why. */
  gateError = $state("");
  gateOpen = $state(!readHandle());

  get signedIn() {
    return Boolean(this.handle) && !this.gateOpen;
  }

  openGate(message = "") {
    this.gateError = message;
    this.gateOpen = true;
  }

  /**
   * Take a handle from the gate. Returns an error string, or null on success —
   * the caller decides how to show it, this decides whether it is allowed.
   */
  signIn(raw) {
    const handle = normalizeHandle(raw);
    if (!handle) return "pick a handle";
    if (isReserved(handle)) return "that handle is reserved";

    this.handle = writeHandle(handle);
    this.gateError = "";
    this.gateOpen = false;
    return null;
  }

  async loadVersion() {
    try {
      this.version = (await api.version()).version;
    } catch {
      /* the badge is decoration; a server too sick to answer will say so elsewhere */
    }
  }

  async loadAdapters() {
    try {
      this.adapters = await api.adapters();
    } catch {
      this.adapters = [];
    }
  }

  async loadPresets() {
    try {
      this.presets = await api.presets();
    } catch {
      this.presets = [];
    }
  }
}

export const session = new Session();
