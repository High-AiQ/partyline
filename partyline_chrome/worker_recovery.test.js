import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture, event, alarms } from './fakes.test.js';
import { HELLO_WAIT, DELAYS } from './backoff.js';

const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
const GREY = '#9aa0a6', RED = '#d93025';

async function boot(tag, { fail = false } = {}) {
  const f = fixture(), ports = [], badge = {};
  const runtime = { onStartup: event(), onInstalled: event(), lastError: null, getManifest: () => ({ version: '1.8.2' }),
    connectNative() {
      if (fail) throw Error('Native host connection refused.');
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
  const w = { f, ports, badge, alarms: f.api.alarms };
  const saved = { info: console.info, warn: console.warn };
  w.act = async fn => { console.info = console.warn = () => {}; try { fn(); await flush(); } finally { Object.assign(console, saved); } };
  await w.act(() => import(`./worker.js?${tag}`));
  w.last = () => ports.at(-1);
  w.hello = () => w.act(() => w.last().onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.8.2' }));
  w.fire = name => w.act(() => w.alarms.fire(name));
  return w;
}

test('a host that starts but never greets is a failed attempt, not "connecting" for ever', async () => {
  const w = await boot('silent-host');
  assert.equal(w.ports.length, 1);
  const hello = w.alarms.pending.get('partyline-hello');
  assert.equal(Math.round((hello.when - Date.now()) / 1000), HELLO_WAIT);
  for (let step = 0; step <= DELAYS.length; step++) { // the first failure retries at once: one more to spend them
    const silent = w.last();
    await w.fire('partyline-hello'); // each silent port ends...
    assert.equal(silent.disconnected, true);
    if (step < DELAYS.length) {
      assert.deepEqual([w.badge.text, w.badge.color], ['…', GREY]);
      if (w.alarms.pending.has('partyline-reconnect')) { // ...and the schedule retries (the first retry is at once)
        assert.match(w.badge.title, /reconnecting to the helper \(the helper bridge did not answer\)/);
        await w.fire('partyline-reconnect');
      }
    }
  }
  assert.deepEqual([w.badge.text, w.badge.color], ['!', RED]); // truly spent: now it asks for a click
  assert.match(w.badge.title, /never answered.*click this button/);
  const count = w.ports.length;
  await w.act(() => w.f.api.action.onClicked.fire());
  assert.equal(w.ports.length, count + 1);
  delete globalThis.chrome;
});

test('a greeting or a closing port clears the hello wait', async () => {
  const w = await boot('hello-clears');
  await w.hello();
  assert.equal(w.alarms.pending.has('partyline-hello'), false);
  assert.equal(w.badge.text, '✓');
  await w.act(() => w.last().remoteDisconnect('Native host has exited.'));
  assert.equal(w.alarms.pending.has('partyline-hello'), true); // the immediate retry opened a new port
  await w.act(() => w.last().remoteDisconnect('Native host has exited.'));
  assert.equal(w.alarms.pending.has('partyline-hello'), false);
  delete globalThis.chrome;
});

test('an older host that holds the helper bridge is named, and the schedule keeps trying', async () => {
  const w = await boot('busy-host');
  await w.act(() => w.last().onMessage.fire({ method: 'Partyline.busy', pid: 4242 }));
  await w.act(() => w.last().remoteDisconnect('Native host has exited.')); // the busy host exits at once
  assert.equal(w.ports.length, 2); // first retry is immediate
  await w.act(() => w.last().onMessage.fire({ method: 'Partyline.busy' }));
  await w.act(() => w.last().remoteDisconnect('Native host has exited.'));
  assert.deepEqual([w.badge.text, w.badge.color], ['…', GREY]);
  assert.match(w.badge.title, /an older helper bridge is still running/);
  await w.fire('partyline-reconnect');
  await w.act(() => w.last().onMessage.fire({ method: 'Partyline.hello', helper_connected: false })); // the old host left
  assert.match(w.badge.title, /waiting for Partyline Helper to attach/);
  await w.hello();
  assert.equal(w.badge.text, '✓');
  delete globalThis.chrome;
});

test('a worker restarted while the port is gone leaves the attempt to its alarm, and the alarm reconnects', async () => {
  const w = await boot('sw-restart');
  await w.hello();
  await w.act(() => w.last().remoteDisconnect('Native host has exited.')); // immediate retry
  await w.act(() => w.last().remoteDisconnect('Native host has exited.')); // fails: a 1 s alarm is armed
  assert.equal(w.alarms.pending.has('partyline-reconnect'), true);
  const count = w.ports.length;
  await w.act(() => import('./worker.js?sw-restart-2')); // Chrome stopped the idle worker and woke it again
  assert.equal(w.ports.length, count); // it did not race the alarm
  await w.fire('partyline-reconnect');
  assert.ok(w.ports.length > count);
  await w.hello();
  assert.deepEqual([w.badge.text, w.badge.color], ['✓', '#1e8e3e']);
  delete globalThis.chrome;
});

test('a helper that quits and a new helper that attaches (server reconnect) never need a click', async () => {
  const w = await boot('helper-reconnect');
  await w.hello();
  for (let i = 0; i < 3; i++) { // the helper's server link drops and returns: the host keeps Chrome's port
    await w.act(() => w.last().onMessage.fire({ method: 'Partyline.reset' }));
    assert.match(w.badge.title, /waiting for Partyline Helper to attach/);
    await w.hello();
    assert.equal(w.badge.text, '✓');
  }
  assert.equal(w.ports.length, 1);
  delete globalThis.chrome;
});

test('Chrome refusing to open the port at all still runs the schedule', async () => {
  const w = await boot('connect-throws', { fail: true });
  assert.deepEqual([w.badge.text, w.badge.color], ['…', GREY]);
  assert.match(w.badge.title, /reconnecting to the helper/);
  delete globalThis.chrome;
});
