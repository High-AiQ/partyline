import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture, event, alarms } from './fakes.test.js';
import { RELEASE_DELAY, DELAYS } from './backoff.js';

const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

async function boot(tag) {
  const f = fixture(), ports = [], badge = {};
  const runtime = { onStartup: event(), onInstalled: event(), lastError: null, getManifest: () => ({ version: '1.8.1' }),
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
  f.api.runtime = runtime;
  f.api.alarms = alarms();
  f.api.storage = { local: { get: async () => ({}), set: async () => {} }, session: f.api.alarms.storage };
  f.api.action = { onClicked: event(), setBadgeText: ({ text }) => { badge.text = text; },
    setBadgeBackgroundColor: ({ color }) => { badge.color = color; }, setTitle: ({ title }) => { badge.title = title; } };
  globalThis.chrome = f.api;
  const quiet = { info: console.info, warn: console.warn };
  console.info = console.warn = () => {};
  try { await import(`./worker.js?${tag}`); await flush(); } finally { Object.assign(console, quiet); }
  const w = { f, ports, badge, alarms: f.api.alarms };
  w.act = async fn => { Object.assign(console, { info() {}, warn() {} }); try { fn(); await flush(); } finally { Object.assign(console, quiet); } };
  w.release = () => w.act(() => ports.at(-1).onMessage.fire({ method: 'Partyline.suspend', release: true }));
  w.hello = () => w.act(() => ports.at(-1).onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.8.1' }));
  w.fireAlarm = () => w.act(() => w.alarms.fire('partyline-reconnect'));
  return w;
}

test('a release does not reconnect at once: one alarm later reconnects with no click', async () => {
  const w = await boot('release-alarm');
  await w.hello();
  await w.release();
  assert.equal(w.ports[0].disconnected, true);
  assert.equal(w.ports.length, 1); // the installer still needs the host's files
  assert.equal(w.alarms.pending.size, 1);
  assert.equal(Math.round((w.alarms.pending.get('partyline-reconnect').when - Date.now()) / 1000), RELEASE_DELAY);
  assert.deepEqual([w.badge.text, w.badge.color], ['…', '#9aa0a6']); // neutral: nothing for the person to do
  assert.match(w.badge.title, /reconnects by itself/);
  await w.act(() => w.f.api.tabs.onActivated.fire({}));
  assert.equal(w.ports.length, 1); // a tab switch during the wait does not respawn the host
  await w.fireAlarm();
  assert.equal(w.ports.length, 2); // the scheduled attempt, no click
  await w.hello();
  assert.equal(w.badge.text, '✓');
  assert.equal(w.alarms.pending.size, 0);
  delete globalThis.chrome;
});

test('a worker restarted during the wait leaves the attempt to the alarm; a click still reconnects at once', async () => {
  const w = await boot('release-restart');
  await w.release();
  await import('./worker.js?release-restart-again'); await flush(); // Chrome stopped and restarted the idle worker
  assert.equal(w.ports.length, 1);
  assert.equal(w.alarms.pending.size, 1);
  await w.act(() => w.f.api.action.onClicked.fire());
  assert.ok(w.ports.length >= 2); // both module instances here listen for the click, as old and new workers never do
  assert.equal(w.alarms.pending.size, 0); // the click ended the wait
  delete globalThis.chrome;
});

test('a plain suspend keeps the port and arms nothing', async () => {
  const w = await boot('plain-suspend');
  await w.hello();
  await w.act(() => w.ports[0].onMessage.fire({ method: 'Partyline.suspend' }));
  assert.equal(w.ports[0].disconnected, false);
  assert.equal(w.alarms.pending.size, 0);
  assert.match(w.badge.title, /waiting for Partyline Helper/);
  delete globalThis.chrome;
});

test('after a release the attempts stay bounded and the click message returns only when they are spent', async () => {
  const w = await boot('release-spent');
  await w.release();
  const gone = 'Native host has exited.';
  const seconds = [];
  for (let step = 0; step < DELAYS.length; step++) {
    await w.fireAlarm();
    await w.act(() => w.ports.at(-1).remoteDisconnect(gone)); // each attempt fails
    assert.deepEqual([w.badge.text, w.badge.color], step < DELAYS.length - 1 ? ['…', '#9aa0a6'] : ['!', '#d93025']);
    if (w.alarms.pending.size) seconds.push(Math.round((w.alarms.pending.get('partyline-reconnect').when - Date.now()) / 1000));
  }
  assert.deepEqual(seconds, [1, 5, 30, 120, 300]);
  assert.equal(w.alarms.pending.size, 0);
  assert.match(w.badge.title, /click this button/);
  const count = w.ports.length;
  await w.act(() => w.f.api.tabs.onActivated.fire({}));
  await w.act(() => w.f.api.action.onClicked.fire());
  assert.equal(w.ports.length, count + 1);
  delete globalThis.chrome;
});
