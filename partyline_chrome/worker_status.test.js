import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture, event, alarms } from './fakes.test.js';

const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

async function boot(tag, { setup } = {}) {
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
  f.api.alarms = alarms();
  f.api.storage = { local: { get: async () => ({ ...saved }), set: async fields => Object.assign(saved, fields) },
    session: f.api.alarms.storage };
  f.api.action = { onClicked: event(),
    setBadgeText: ({ text }) => { badge.text = text; badge.history.push(text); },
    setBadgeBackgroundColor: ({ color }) => { badge.color = color; },
    setTitle: ({ title }) => { badge.title = title; } };
  setup?.(f.api);
  globalThis.chrome = f.api;
  const saveInfo = console.info, saveWarn = console.warn;
  console.info = (...a) => logs.push(['info', a.join(' ')]);
  console.warn = (...a) => logs.push(['warn', a.join(' ')]);
  try { await import(`./worker.js?${tag}`); await flush(); } finally { console.info = saveInfo; console.warn = saveWarn; }
  return { f, ports, badge, logs, runtime, saved, alarms: f.api.alarms,
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

test('registration and id mismatches are red at once with their reason, and a click retries at once', async () => {
  const w = await boot('badge-errors');
  const cases = [['Specified native messaging host not found.', /Reinstall or restart Partyline Helper/],
    ['Access to the specified native messaging host is forbidden.', /extension id mismatch/]];
  for (const [error, expected] of cases) {
    const port = w.ports.at(-1), before = w.ports.length;
    await w.fire(port, p => p.remoteDisconnect(error));
    assert.deepEqual([w.badge.text, w.badge.color], ['!', '#d93025']);
    assert.match(w.badge.title, expected);
    assert.ok(w.logs.some(([level, line]) => level === 'warn' && line.includes(error)));
    await w.click(); // immediate retry: connecting is shown before Chrome answers
    assert.equal(w.ports.length, before + 1);
    assert.equal(w.badge.text, '…');
    assert.equal(w.alarms.pending.size, 0); // a click ends the schedule
  }
  delete globalThis.chrome;
});

test('a host that exits is retried on a bounded schedule: grey while it runs, red only when it is spent', async () => {
  const w = await boot('badge-schedule');
  const gone = 'Native host has exited.';
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.6.2' }));
  await w.fire(w.ports[0], p => p.remoteDisconnect(gone)); // the host went away: one try at once, no click
  assert.equal(w.ports.length, 2);
  assert.deepEqual([w.badge.text, w.badge.color], ['…', '#9aa0a6']);
  const seconds = [];
  for (let step = 0; step < 5; step++) {
    await w.fire(w.ports.at(-1), p => p.remoteDisconnect(gone)); // each try fails: neutral, an alarm is armed
    assert.deepEqual([w.badge.text, w.badge.color], ['…', '#9aa0a6']);
    assert.match(w.badge.title, /reconnecting to the helper \(the helper bridge stopped\)/);
    const when = w.alarms.pending.get('partyline-reconnect').when;
    seconds.push(Math.round((when - Date.now()) / 1000));
    const count = w.ports.length;
    await w.fire(w.ports.at(-1), () => w.alarms.fire('partyline-reconnect')); // the alarm, not a click, tries again
    assert.equal(w.ports.length, count + 1);
  }
  assert.deepEqual(seconds, [1, 5, 30, 120, 300]);
  await w.fire(w.ports.at(-1), p => p.remoteDisconnect(gone)); // the schedule is spent
  assert.deepEqual([w.badge.text, w.badge.color], ['!', '#d93025']);
  assert.match(w.badge.title, /helper bridge stopped/);
  assert.equal(w.alarms.pending.size, 0);
  const count = w.ports.length;
  await w.fire(w.ports.at(-1), () => {});
  assert.equal(w.ports.length, count); // nothing keeps trying by itself
  await w.click();
  assert.equal(w.ports.length, count + 1); // a click starts over
  await w.fire(w.ports.at(-1), p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.7.1' }));
  assert.equal(w.badge.text, '✓');
  await w.fire(w.ports.at(-1), p => p.remoteDisconnect(gone)); // a greeting ended the schedule: it starts again
  assert.equal(w.ports.length, count + 2);
  delete globalThis.chrome;
});

test('an unplanned port loss while still starting retries too: a worker that starts as the helper restarts', async () => {
  const w = await boot('badge-restarting');
  await w.fire(w.ports[0], p => p.remoteDisconnect('Native host has exited.')); // never greeted
  assert.equal(w.ports.length, 2); // the first retry is at once
  await w.fire(w.ports[1], p => p.remoteDisconnect('Native host has exited.'));
  assert.equal(w.alarms.pending.get('partyline-reconnect').when > Date.now(), true);
  await w.fire(w.ports[1], () => w.alarms.fire('partyline-reconnect'));
  await w.fire(w.ports[2], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.7.1' }));
  assert.deepEqual([w.badge.text, w.badge.color], ['✓', '#1e8e3e']);
  assert.equal(w.alarms.pending.size, 0);
  delete globalThis.chrome;
});

test('a tab activation retries once when the schedule is spent, never while an alarm waits or right after a try', async () => {
  const w = await boot('badge-activation');
  const realNow = Date.now;
  let now = realNow();
  Date.now = () => now;
  try {
    for (let i = 0; i < 7; i++) {
      await w.fire(w.ports.at(-1), p => p.remoteDisconnect('Native host has exited.'));
      if (w.alarms.pending.size) await w.fire(w.ports.at(-1), () => w.alarms.fire('partyline-reconnect'));
    }
    assert.equal(w.badge.text, '!');
    const count = w.ports.length;
    w.f.api.tabs.onActivated.fire({}); await flush();
    assert.equal(w.ports.length, count); // too soon after the last try
    now += 31_000;
    w.f.api.tabs.onActivated.fire({}); await flush();
    assert.equal(w.ports.length, count + 1);
    assert.equal(w.badge.text, '…'); // attempting
    w.f.api.tabs.onActivated.fire({}); await flush();
    assert.equal(w.ports.length, count + 1); // one port at a time
  } finally { Date.now = realNow; }
  delete globalThis.chrome;
});

test('an installer release shows paused; clicking a connected button refreshes it; a silent stale port is replaced', async () => {
  const w = await boot('badge-suspend');
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.suspend', release: true }));
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
  assert.ok(w.logs.some(([, line]) => /no helper is attached; reconnecting/.test(line)));
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

const hello = { method: 'Partyline.hello', helper_connected: true, helper_version: '1.6.2' };

test('a helper that quits or pauses leaves the native port up, grey, and its return needs no click', async () => {
  const w = await boot('badge-away');
  await w.fire(w.ports[0], p => p.onMessage.fire(hello));
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.reset' })); // helper quit
  assert.equal(w.ports.length, 1);
  assert.equal(w.ports[0].disconnected, false);
  assert.deepEqual([w.badge.text, w.badge.color], ['…', '#9aa0a6']);
  assert.match(w.badge.title, /waiting for Partyline Helper to attach/);
  await w.fire(w.ports[0], p => p.onMessage.fire(hello)); // the restarted helper attaches: no click
  assert.deepEqual([w.badge.text, w.badge.color], ['✓', '#1e8e3e']);
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.suspend' })); // update pause, no release
  assert.equal(w.ports[0].disconnected, false);
  assert.match(w.badge.title, /waiting for Partyline Helper/);
  await w.fire(w.ports[0], p => p.onMessage.fire(hello)); // update done
  assert.equal(w.badge.text, '✓');
  assert.equal(w.ports.length, 1);
  delete globalThis.chrome;
});

test('clicking while the helper is away starts over with a new native port', async () => {
  const w = await boot('badge-away-click');
  await w.fire(w.ports[0], p => p.onMessage.fire(hello));
  await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.reset' }));
  await w.click();
  assert.equal(w.ports.length, 2);
  assert.equal(w.ports[0].disconnected, true);
  assert.equal(w.badge.text, '…');
  assert.ok(w.logs.some(([, line]) => /no helper is attached; reconnecting/.test(line)));
  delete globalThis.chrome;
});

test('a hello queued behind a closed port cannot repaint or reset the replacement port', async () => {
  const w = await boot('badge-stale-hello');
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  w.f.api.debugger.detach = async d => { w.f.calls.push(['detach', d]); await gate; };
  const first = w.ports[0];
  await w.fire(first, p => p.onMessage.fire(hello));
  await w.fire(first, p => {
    p.onMessage.fire({ id: 1, method: 'Partyline.scope', grant: 'g', params: { tabs: [1], windowId: 9 } });
    p.onMessage.fire({ id: 2, method: 'Partyline.begin', grant: 'g' });
    p.onMessage.fire({ id: 3, method: 'Target.attachToTarget', grant: 'g', params: { targetId: '1' } });
  });
  await w.fire(first, p => { p.onMessage.fire(hello); p.onMessage.fire(hello); }); // reset waits on the detach
  await w.fire(first, p => p.remoteDisconnect('Native host has exited.')); // the port closes, a retry waits
  release();
  await w.fire(first, () => {});
  assert.equal(w.ports.length, 2);
  assert.deepEqual([w.badge.text, w.badge.color], ['…', '#9aa0a6']); // the new port never greeted: not green
  assert.match(w.badge.title, /connecting/);
  await w.fire(w.ports[1], p => p.onMessage.fire(hello));
  assert.equal(w.badge.text, '✓');
  delete globalThis.chrome;
});

test('automatic update: stop, host exit, new host and helper bring the badge back to green with no click', async () => {
  for (const [tag, reset] of [['update-1-7', true], ['update-1-6-host-dies', false]]) {
    const w = await boot(tag);
    const gone = 'Native host has exited.';
    await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.6.1' }));
    assert.equal(w.badge.text, '✓');
    // `stop` on the old helper: a 1.7 host tells the extension the helper is away; a 1.6.x host just dies.
    if (reset) await w.fire(w.ports[0], p => p.onMessage.fire({ method: 'Partyline.reset' }));
    // The installer replaces files: the old host process exits, so Chrome closes its port.
    await w.fire(w.ports[0], p => p.remoteDisconnect(gone));
    assert.equal(w.ports.length, 2); // the first reconnect is at once
    await w.fire(w.ports[1], p => p.remoteDisconnect(gone)); // the new host is not up yet
    assert.deepEqual([w.badge.text, w.badge.color], ['…', '#9aa0a6']); // never red while attempts remain
    await w.fire(w.ports[1], () => w.alarms.fire('partyline-reconnect')); // the 1 s alarm
    await w.fire(w.ports[2], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: false }));
    assert.match(w.badge.title, /waiting for Partyline Helper/);
    await w.fire(w.ports[2], p => p.onMessage.fire({ method: 'Partyline.hello', helper_connected: true, helper_version: '1.7.1' }));
    assert.deepEqual([w.badge.text, w.badge.color], ['✓', '#1e8e3e']);
    assert.equal(w.alarms.pending.size, 0);
    assert.ok(w.logs.every(([, line]) => !/click/.test(line) || !/toolbar click/.test(line))); // no click happened
    delete globalThis.chrome;
  }
});

test('a worker restarted mid-schedule leaves the next attempt to its pending alarm', async () => {
  const w = await boot('mid-schedule', { setup: api => {
    api.alarms.storage.set({ reconnect: { failures: 4, last: 0 } });
    api.alarms.pending.set('partyline-reconnect', { when: Date.now() + 120_000 });
  } });
  assert.equal(w.ports.length, 0); // no port until the alarm, a click, a browser start or a tab activation
  await w.fire(null, () => w.alarms.fire('partyline-reconnect'));
  assert.equal(w.ports.length, 1);
  delete globalThis.chrome;
});

test('a worker restarted after the schedule was spent does not connect by itself', async () => {
  const w = await boot('spent-schedule', { setup: api => { api.alarms.storage.set({ reconnect: { failures: 6, last: 0 } }); } });
  assert.equal(w.ports.length, 0);
  await w.click();
  assert.equal(w.ports.length, 1);
  delete globalThis.chrome;
});

test('a startup and an alarm that wake the worker together open one native port, even with storage still loading', async () => {
  let release;
  const w = await boot('racing-wake', { setup: api => {
    api.alarms.storage.set({ reconnect: { failures: 1, last: 0 } });
    const slow = new Promise(resolve => { release = resolve; });
    const get = api.alarms.storage.get;
    api.storage.session = { ...api.alarms.storage, get: async () => { await slow; return get(); } };
  } });
  w.f.api.alarms.onAlarm.fire({ name: 'partyline-reconnect' }); // the alarm that woke the worker
  w.f.api.alarms.onAlarm.fire({ name: 'partyline-reconnect' }); // and another event that arrives with it
  await flush();
  assert.equal(w.ports.length, 0); // everything waits for the persisted schedule
  release();
  await flush();
  assert.equal(w.ports.length, 1);
  delete globalThis.chrome;
});
