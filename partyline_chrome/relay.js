import { Attachments, safeURL } from './attachments.js';
import { chromeFailure, codeOf, refuse } from './refusal.js';

export class Relay {
  constructor(api, emit, clock) {
    this.api = api;
    this.emit = message => {
      try { emit(message); } catch { /* a dead native port must never interrupt revoke cleanup */ }
    };
    this.attachments = new Attachments(api, this.emit, clock);
    api.debugger.onEvent.addListener((...args) => this.attachments.event(...args));
    api.debugger.onDetach.addListener((...args) => this.attachments.detached(...args));
    const movedOrRemoved = tabId => {
      for (const entry of this.attachments.entries.values()) {
        if (entry.tabId === tabId) this.attachments.forget(entry);
      }
    };
    api.tabs.onAttached.addListener(movedOrRemoved);
    api.tabs.onRemoved.addListener(movedOrRemoved);
    api.tabs.onUpdated.addListener((tabId, changes) => {
      if (changes.url && !safeURL(changes.url)) {
        for (const entry of this.attachments.entries.values()) {
          if (entry.tabId === tabId) this.attachments.forget(entry);
        }
      }
    });
  }
  async receive(message) {
    try {
      const result = await this.command(message);
      this.emit({ id: message.id, result: result || {} });
    } catch (error) {
      this.emit({ id: message.id, error: { message: 'Extension command refused or interrupted',
        code: codeOf(error) } });
    }
  }
  async command({ method, params = {}, sessionId, grant }) {
    if (method === 'Partyline.dispatch') return this.command(params);
    const a = this.attachments;
    if (method === 'Target.setDiscoverTargets') return {}; // tab events stay inside granted sessions
    if (method === 'Browser.getVersion') return { product: 'Partyline Chrome extension' };
    if (method === 'Partyline.windows') {
      const windows = await this.api.windows.getAll({ populate: true, windowTypes: ['normal'] });
      return { windows: windows.map(w => ({ id: w.id, left: w.left, top: w.top, width: w.width,
        height: w.height, focused: w.focused, state: w.state,
        tabs: w.tabs.filter(t => safeURL(t.url)).map(t => ({ id: t.id, windowId: t.windowId,
          active: t.active, url: t.url, title: t.title })) })) };
    }
    if (method === 'Partyline.scope') { a.scope(grant, params.tabs, params.windowId); return {}; }
    if (method === 'Partyline.begin') { a.held.add(grant); return {}; }
    if (method === 'Partyline.end') { a.release(grant); return {}; }
    if (method === 'Partyline.revoke') return await a.revoke(grant), {};
    if (method === 'Partyline.reset') return await a.reset(), {};
    if (method === 'Partyline.release') return await a.drop(params.tabs, params.live);
    if (method === 'Partyline.metrics') return a.metrics;
    if (method === 'Target.attachToTarget' && !sessionId) {
      const entry = await a.attach(grant, Number(params.targetId));
      a.idle(entry);
      return { sessionId: entry.session };
    }
    if (method === 'Partyline.resume') return await a.resume(a.entry(params.sessionId));
    if (method === 'Target.detachFromTarget' && !sessionId) {
      const entry = a.entry(params.sessionId);
      if (entry.session === params.sessionId) return await a.forget(entry), {};
      return await this.api.debugger.sendCommand({ tabId: entry.tabId }, method, params);
    }
    const entry = a.entry(sessionId);
    if (method === 'Page.navigate' && !safeURL(params.url)) throw refuse('restricted_navigation');
    // Browser/Target commands cannot escape the tab capability via a granted root session.
    if (!/^(Page|DOM|Accessibility|Runtime|Input|Inspector)\./.test(method) &&
        !['Target.setAutoAttach', 'Target.detachFromTarget'].includes(method)) throw refuse('domain_refused');
    if (method === 'Target.setAutoAttach') {
      params = { ...params, flatten: true, filter: [{ type: 'iframe', exclude: false }, { exclude: true }] };
    }
    if (method === 'Target.detachFromTarget' && !entry.children.has(params.sessionId)) {
      throw refuse('child_outside_grant');
    }
    entry.busy = (entry.busy || 0) + 1;
    try {
      await a.resume(entry);
      await a.check(entry);
      const debuggee = { tabId: entry.tabId };
      if (sessionId !== entry.session) {
        if (!entry.children.has(sessionId)) throw refuse('child_detached');
        debuggee.sessionId = sessionId;
      }
      if (!a.valid(entry)) throw refuse('revoked');
      return await this.api.debugger.sendCommand(debuggee, method, params)
        .catch(error => { throw chromeFailure(error, 'debugger_command_failed'); });
    } finally {
      entry.busy--;
      a.idle(entry);
    }
  }
}
