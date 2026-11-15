// An attachment is a revocable capability, never a browser-wide connection.
import { chromeFailure, refuse } from './refusal.js';

export const IDLE_LINGER_MS = 300;
export const safeURL = (url) => /^https?:/i.test(url || '');

export class Attachments {
  constructor(api, emit, clock = globalThis) {
    this.api = api;
    this.emit = emit;
    this.clock = clock;
    this.entries = new Map();
    this.serial = 0;
    this.orphans = new Set();
    this.grants = new Map();
    this.cancelled = new Set();
    this.held = new Set();
    this.windows = new Map();
    this.metrics = { attach_ms: [], detach_ms: [] };
  }
  now() { return this.clock.performance.now(); }
  scope(grant, tabs, windowId) {
    if (typeof grant !== 'string' || !grant || !Array.isArray(tabs) || !tabs.every(Number.isInteger) || !Number.isInteger(windowId)) {
      throw refuse('tab_outside_grant');
    }
    if (this.cancelled.has(grant)) throw refuse('revoked'); // cancelled by the user; a new share is required
    const allowed = new Set(tabs);
    for (const entry of this.entries.values()) {
      if (entry.grant === grant && !allowed.has(entry.tabId)) this.forget(entry);
    }
    this.grants.set(grant, allowed);
    this.windows.set(grant, windowId);
  }
  valid(entry) {
    return this.entries.get(entry.session) === entry && this.grants.get(entry.grant)?.has(entry.tabId);
  }
  async check(entry) {
    if (!this.valid(entry)) throw refuse('revoked');
    const tab = await this.api.tabs.get(entry.tabId).catch(() => { throw refuse('tab_outside_grant'); });
    if (!this.valid(entry)) throw refuse('revoked');
    if (tab.windowId !== this.windows.get(entry.grant)) throw refuse('tab_outside_grant');
    if (!safeURL(tab.url) || (tab.pendingUrl && !safeURL(tab.pendingUrl))) throw refuse('restricted_navigation');
    return tab;
  }
  async attach(grant, tabId) {
    if (!this.grants.get(grant)?.has(tabId)) throw refuse('tab_outside_grant');
    // A detach that failed earlier gets one more try now; only a tab Chrome still holds blocks the new grant.
    for (const orphan of [...this.orphans].filter(e => e.tabId === tabId)) await this.detach(orphan).catch(() => {});
    if ([...this.orphans].some(e => e.tabId === tabId)) throw refuse('previous_detach_incomplete');
    // One debugger per tab. Two independently revocable grants cannot share it.
    if ([...this.entries.values()].some(e => e.tabId === tabId && e.grant !== grant)) {
      throw refuse('tab_owned_by_other_grant');
    }
    const previous = [...this.entries.values()].find(e => e.tabId === tabId && e.grant === grant);
    if (previous) await this.forget(previous);
    const session = `${grant}:${tabId}:${++this.serial}`;
    const entry = { grant, tabId, session, attached: false, pending: null, timer: null, children: new Set() };
    this.entries.set(session, entry);
    await this.resume(entry);
    return entry;
  }
  async resume(entry) {
    this.clock.clearTimeout(entry.timer);
    if (entry.closing) await entry.closing;
    await this.check(entry);
    if (entry.pending) return entry.pending;
    if (entry.attached) return { reattached: false };
    entry.pending = this.open(entry);
    try { return await entry.pending; }
    finally { entry.pending = null; }
  }
  async open(entry) {
    const start = this.now();
    await this.api.debugger.attach({ tabId: entry.tabId }, '1.3').catch(error => {
      throw chromeFailure(error, 'debugger_attach_failed');
    });
    entry.attached = true;
    this.metrics.attach_ms.push(this.now() - start);
    this.metrics.attach_ms.splice(0, Math.max(0, this.metrics.attach_ms.length - 128));
    if (!this.valid(entry)) {
      await this.detach(entry);
      throw refuse('revoked');
    }
    try {
      await this.check(entry);
      const result = await this.api.debugger.sendCommand({ tabId: entry.tabId }, 'Page.getFrameTree')
        .catch(error => { throw chromeFailure(error, 'debugger_command_failed'); });
      const loader = result.frameTree.frame.loaderId;
      const documentChanged = entry.loader !== undefined && entry.loader !== loader;
      entry.loader = loader;
      this.emit({ method: 'Partyline.attachment', sessionId: entry.session, params: { attached: true } });
      return { reattached: true, documentChanged };
    } catch (error) {
      await this.detach(entry);
      throw error;
    }
  }
  release(grant) {
    this.held.delete(grant);
    for (const entry of this.entries.values()) if (entry.grant === grant) this.idle(entry);
  }
  idle(entry) {
    this.clock.clearTimeout(entry.timer);
    if (entry.attached && !this.held.has(entry.grant) && !entry.busy) {
      // no-poll (b): one-shot idle deadline, reset by actual operations.
      entry.timer = this.clock.setTimeout(() => { void this.detach(entry).catch(() => {}); }, IDLE_LINGER_MS);
    }
  }
  async detach(entry) {
    if (entry.closing) return entry.closing;
    this.clock.clearTimeout(entry.timer);
    entry.children.clear();
    if (!entry.attached) return;
    entry.attached = false;
    this.emit({ method: 'Partyline.attachment', sessionId: entry.session, params: { attached: false } });
    const start = this.now();
    entry.closing = this.api.debugger.detach({ tabId: entry.tabId });
    try { await entry.closing; this.orphans.delete(entry); }
    catch (error) {
      if (chromeFailure(error, '').code === 'debugger_detached') { this.orphans.delete(entry); return; }
      // Retain ownership after an API failure so revoke or the next release can still detach.
      entry.attached = true;
      this.emit({ method: 'Partyline.attachment', sessionId: entry.session,
        params: { attached: true, detachFailed: true } });
      throw error;
    }
    finally {
      this.metrics.detach_ms.push(this.now() - start);
      this.metrics.detach_ms.splice(0, Math.max(0, this.metrics.detach_ms.length - 128));
      entry.closing = null;
    }
  }
  forget(entry) {
    this.entries.delete(entry.session); // gate first, before the asynchronous Chrome API
    return this.detach(entry).catch(() => { this.orphans.add(entry); });
  }
  revoke(grant) {
    this.grants.delete(grant);
    this.windows.delete(grant);
    this.held.delete(grant);
    return Promise.all([...this.entries.values(), ...this.orphans]
      .filter(e => e.grant === grant).map(e => this.forget(e)));
  }
  // Release a tab's entries under grants the helper no longer has; a live grant's tab is never touched.
  async drop(tabs, live) {
    if (!Array.isArray(tabs) || !tabs.every(Number.isInteger) || !Array.isArray(live)) throw refuse('tab_outside_grant');
    const wanted = new Set(tabs), keep = new Set(live);
    const stale = [...this.entries.values(), ...this.orphans].filter(e => wanted.has(e.tabId) && !keep.has(e.grant));
    await Promise.all(stale.map(e => this.forget(e)));
    return { released: stale.length };
  }
  reset() {
    const grants = new Set([...this.grants.keys(), ...[...this.orphans].map(e => e.grant)]);
    return Promise.all([...grants].map(g => this.revoke(g)));
  }
  entry(session) {
    const entry = this.entries.get(session) || [...this.entries.values()].find(e => e.children.has(session));
    if (!entry || !this.valid(entry)) throw refuse('revoked');
    return entry;
  }
  event(source, method, params) {
    const entry = [...this.entries.values()].find(e => e.tabId === source.tabId && e.attached);
    if (!entry || !this.valid(entry) || (source.sessionId && !entry.children.has(source.sessionId))) return;
    if (method === 'Target.attachedToTarget') {
      if (params.targetInfo.type !== 'iframe' || !safeURL(params.targetInfo.url)) {
        void this.api.debugger.sendCommand(source, 'Target.detachFromTarget',
          { sessionId: params.sessionId }).catch(() => {});
        return;
      }
      entry.children.add(params.sessionId);
    }
    this.emit({ method, params, sessionId: source.sessionId || entry.session });
    if (method === 'Target.detachedFromTarget') entry.children.delete(params.sessionId);
  }
  detached(source, reason) {
    const entry = [...this.entries.values()].find(e => e.tabId === source.tabId);
    if (!entry || !entry.attached) return; // our idle detach preserves the root capability
    entry.attached = false; // Chrome's notification is authoritative; do not detach an already gone target
    if (reason === 'canceled_by_user') {
      this.cancelled.add(entry.grant);
      void this.revoke(entry.grant);
      this.emit({ method: 'Partyline.grantCancelled', params: { grant: entry.grant } });
    } else this.forget(entry);
    this.emit({ method: 'Target.detachedFromTarget', params: { sessionId: entry.session, reason } });
    this.emit({ method: 'Inspector.detached', params: { reason }, sessionId: entry.session });
  }
}
