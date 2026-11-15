import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture, event } from './fakes.test.js';

const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

async function boot(tag, { throwNotFound = false } = {}) {
  const f = fixture(), ports = [], badge = { history: [] }, logs = [];
  const runtime = { onStartup: event(), onInstalled: event(), lastError: null,
    getManifest: () => ({ version: '1.6.2' }), reload() { badge.reloaded = true; },
    connectNative() {
      const port = { onMessage: event(), onDisconnect: event(), disconnected: false, sent: [],
        postMessage(m) { this.sent.push(m); }, disconnect() { this.disconnected = true; },
        remoteDisconnect(error) {
          runtime.lastError = error ? { message: error } : null;
          this.disconnected = true; this.onDisconnect.fire(); runtime.lastError = null;
        } };
      ports.push(port);
      return port;
    } };
  const saved = {};
  f.api.runtime = runtime;
  f.api.storage = { local: { get: async () => ({ ...saved }), set: async fields => Object.assign(saved, fields) } };
  f.api.action = { onClicked: event(),
    setBadgeText: ({ text }) => { badge.text = text; badge.history.push(text); },
    setBadgeBackgroundColor: ({ color }) => { badge.color = color; },
    setTitle: ({ title }) => { badge.title = title; } };
  globalThis.chrome = f.api;
  const saveInfo = console.info, saveWarn = console.warn;
  console.info = (...a) => logs.push(['info', a.join(' ')]);
  console.warn = (...a) => logs.push(['warn', a.join(' ')]);
  try { await import(`./worker.js?${tag}`); await flush(); } finally { console.info = saveInfo; console.warn = saveWarn; }
  return { f, ports, badge, logs, runtime, saved,
    async click() { const i = console.info, w = console.warn;
      console.info = (...a) => logs.push(['info', a.join(' ')]); console.warn = (...a) => logs.push(['warn', a.join(' ')]);
      try { f.api.action.onClicked.fire(); await flush(); } finally { console.info = i; console.warn = w; } },
    async fire(port, fn) { const i = console.info, w = console.warn;
      console.info = (...a) => logs.push(['info', a.join(' ')]); console.warn = (...a) => logs.push(['warn', a.join(' ')]);
      try { fn(port); await flush(); } finally { console.info = i; console.warn = w; } } };
}

test('badge goes connecting, waiting for the helper, then green with the helper version', async () => {
  const w = await boot('badge-flow');
  assert.equal(w.badge.text, '…');
  assert.match(w.badge.title, /connecting/);
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: false }));
  assert.match(w.badge.title, /waiting for Partyline Helper/);
  assert.equal(w.badge.text, '…'); // a host alone is not "connected": no helper has attached
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.6.2' }));
  assert.deepEqual([w.badge.text, w.badge.color], ['✓', '#1e8e3e']);
  assert.equal(w.badge.title, 'Partyline: connected to helper 1.6.2');
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.reset' }));
  assert.match(w.badge.title, /waiting for Partyline Helper/);
  assert.ok(w.logs.some(([level, line]) => level === 'info' && /helper 1\.6\.2 attached/.test(line)));
  delete globalThis.chrome;
});

test('every Chrome failure turns the badge red with its reason, and a click retries at once', async () => {
  const w = await boot('badge-errors');
  const cases = [['Specified native messaging host not found.', /Reinstall or restart Partyline Helper/],
    ['Access to the specified native messaging host is forbidden.', /extension id mismatch/],
    ['Native host has exited.', /helper bridge stopped/]];
  for (const [error, expected] of cases) {
    const port = w.ports.at(-1), before = w.ports.length;
    await w.fire(port, p => p.remoteDisconnect(error));
    assert.deepEqual([w.badge.text, w.badge.color], ['!', '#d93025']);
    assert.match(w.badge.title, expected);
    assert.ok(w.logs.some(([level, line]) => level === 'warn' && line.includes(error)));
    await w.click(); // immediate retry: connecting is shown before Chrome answers
    assert.equal(w.ports.length, before + 1);
    assert.equal(w.badge.text, '…');
  }
  // Disconnected after having been greeted: one automatic retry, then red.
  const port = w.ports.at(-1);
  port.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.6.2' });
  await flush();
  const count = w.ports.length;
  await w.fire(port, p => p.remoteDisconnect(''));
  assert.equal(w.ports.length, count + 1);
  await w.fire(w.ports.at(-1), p => p.remoteDisconnect(''));
  assert.match(w.badge.title, /helper bridge stopped/);
  delete globalThis.chrome;
});

test('suspend shows paused; clicking a connected button refreshes it; a silent stale port is replaced', async () => {
  const w = await boot('badge-suspend');
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.suspend' }));
  assert.equal(w.ports[0].disconnected, true);
  assert.match(w.badge.title, /paused for a helper update/);
  await w.click();
  assert.equal(w.ports.length, 2);
  await w.fire(w.ports[1], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.6.2' }));
  w.badge.title = '';
  await w.click(); // already connected and greeted: no new port, the badge is repainted
  assert.equal(w.ports.length, 2);
  assert.equal(w.badge.title, 'Partyline: connected to helper 1.6.2');
  w.ports[1].onMessage.fire({ chunk: { index: 9, total: 2, data: '' } }); // unreadable
  assert.match(w.badge.title, /unreadable/);
  await w.click();
  assert.equal(w.ports.length, 3); // never greeted, so a click replaces it instead of doing nothing
  await w.click();
  assert.equal(w.ports.length, 4);
  assert.equal(w.ports[2].disconnected, true);
  assert.ok(w.logs.some(([, line]) => /never greeted/.test(line)));
  delete globalThis.chrome;
});

test('reload decisions and logs carry versions only, never page content or command payloads', async () => {
  const w = await boot('badge-reload');
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true,
    helper_version: '1.7.0', extension_version: '1.7.0', auto_update: true }));
  assert.equal(w.badge.reloaded, true);
  assert.ok(w.logs.some(([, line]) => /reloading the extension: running 1\.6\.2, helper ships 1\.7\.0/.test(line)));
  const secret = 'https://private.example/page?token=abc';
  const alive = await boot('badge-payload');
  await alive.fire(alive.ports[0], p => {
    p.onMessage.fire({ id: 1, method: 'Runtime.evaluate', params: { expression: secret } });
  });
  assert.ok(alive.logs.length > 0);
  assert.ok(alive.logs.every(([, line]) => !line.includes(secret) && !line.includes('abc')));
  delete globalThis.chrome;
});
