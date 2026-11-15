import { performance } from 'node:perf_hooks';
export function event() {
  const listeners = [];
  return { addListener: f => listeners.push(f), fire: (...a) => listeners.forEach(f => f(...a)) };
}
export function fixture() {
  const timers = new Map();
  let now = 0, serial = 0;
  const clock = { performance: { now: () => now },
    setTimeout(f, ms) { const id = ++serial; timers.set(id, { f, at: now + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    advance(ms) { now += ms; for (const [id, t] of timers) if (t.at <= now) { timers.delete(id); t.f(); } },
  };
  const tabs = new Map([[1, { id: 1, url: 'https://example.test', title: 'Lab', active: true, windowId: 9 }],
    [2, { id: 2, url: 'chrome://settings', title: 'Settings', windowId: 9 }]]);
  const calls = [], messages = [];
  const api = {
    tabs: { get: async id => { if (!tabs.has(id)) throw Error('Missing'); return tabs.get(id); }, onUpdated: event(), onAttached: event(), onRemoved: event(), onActivated: event() },
    windows: { getAll: async () => [{ id: 9, left: 10, top: 20, width: 800, height: 600,
      focused: true, state: 'normal', tabs: [...tabs.values()] }] },
    debugger: { onEvent: event(), onDetach: event(),
      attach: async d => { calls.push(['attach', d]); now += 7; },
      detach: async d => { calls.push(['detach', d]); now += 3; },
      sendCommand: async (d, method, params) => {
        calls.push([method, d, params]);
        if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'root', loaderId: api.loader } } };
        return { ok: true };
      },
    }, loader: 'document-1',
  };
  return { api, clock, tabs, calls, messages, performance };
}
// chrome.alarms and chrome.storage.session: alarms never fire by themselves; the test fires them.
export function alarms() {
  const pending = new Map(), listeners = event(), session = {};
  return { pending, onAlarm: listeners,
    create: async (name, info) => { pending.set(name, info); },
    clear: async name => pending.delete(name),
    get: async name => pending.get(name),
    fire(name) { assert(pending.delete(name), `no ${name} alarm is pending`); listeners.fire({ name }); },
    storage: { get: async () => ({ ...session }), set: async fields => Object.assign(session, fields) } };
}
function assert(ok, message) { if (!ok) throw Error(message); }
