/**
 * The authenticated operator, and the things that belong to the server rather
 * than to a line: the adapter registry, saved presets, and version badge.
 */

import { api } from "../lib/api";
import type { Adapter, AuthTokenResponse, AuthUser, Preset } from "../lib/contracts";
import {
  clearStoredTokens,
  configureAuthHandlers,
  isAuthStorageKey,
  readAccessToken,
  storeTokens,
} from "../lib/http";
import { readOrMintClientId } from "../lib/identity";

class Session {
  user = $state<AuthUser | null>(null);
  authReady = $state(false);
  clientId = readOrMintClientId();
  version = $state<string | null>(null);
  instanceName = $state<string | null>(null);

  adapters = $state<Adapter[]>([]);
  presets = $state<Preset[]>([]);

  get handle(): string | null {
    return this.user?.handle ?? null;
  }

  get signedIn(): boolean {
    return this.authReady && this.user !== null;
  }

  async register(email: string, password: string, handle: string): Promise<void> {
    this.acceptTokens(await api.register({ email, password, handle }));
  }

  async login(email: string, password: string): Promise<void> {
    this.acceptTokens(await api.login({ email, password }));
  }

  async changeHandle(handle: string): Promise<void> {
    this.user = await api.changeHandle({ handle });
  }

  /** Validate a cached access token without letting an old request clobber a
   *  login that completed while `/me` was in flight. */
  async loadCurrentUser(): Promise<void> {
    const startedWith = readAccessToken();
    if (!startedWith) {
      this.user = null;
      this.authReady = true;
      return;
    }
    try {
      const user = await api.me();
      if (readAccessToken() === startedWith) this.user = user;
    } catch {
      // The transport clears only on an unrecoverable 401. A network or
      // contract failure must not destroy a still-valid persisted session.
    } finally {
      this.authReady = true;
    }
  }

  logout(): void {
    this.clearSession();
  }

  acceptTokens(tokens: AuthTokenResponse): void {
    storeTokens(tokens.access_token, tokens.refresh_token);
    this.user = tokens.user;
    this.authReady = true;
  }

  clearSession(): void {
    clearStoredTokens();
    this.user = null;
    this.authReady = true;
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
  acceptHandshake(version: string, instanceName: string | null, handle: string): void {
    this.acceptServerVersion(version);
    this.instanceName = instanceName;
    if (this.user && this.user.handle !== handle) this.user = { ...this.user, handle };
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

configureAuthHandlers({
  onRefreshed: (tokens) => {
    session.user = tokens.user;
  },
  onSessionCleared: () => {
    session.clearSession();
  },
});

// Tokens are shared between tabs; keep the in-memory user equally shared.
// Storage events fire only in the other documents, never the writer itself.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.storageArea === localStorage && isAuthStorageKey(event.key)) {
      void session.loadCurrentUser();
    }
  });
}
