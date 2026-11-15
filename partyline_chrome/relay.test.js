import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { fixture } from './fakes.test.js';
import { Relay } from './relay.js';
import { IDLE_LINGER_MS } from './attachments.js';

function setup() {
  const f = fixture();
  f.relay = new Relay(f.api, m => f.messages.push(m), f.clock);
  f.command = (method, params = {}, sessionId) => f.relay.command({ method, params: { windowId: 9, ...params }, sessionId, grant: 'g' });
  f.attach = async () => {
    await f.command('Partyline.scope', { tabs: [1] });
    return (await f.command('Target.attachToTarget', { targetId: '1' })).sessionId;
  };
  return f;
}

test('minimal manifest and tab/window queries do not attach', async () => {
  const manifest = JSON.parse(await (await import('node:fs/promises')).readFile(new URL('./manifest.json', import.meta.url)));
  assert.deepEqual(manifest.permissions, ['debugger', 'tabs', 'nativeMessaging', 'alarms', 'storage']);
  assert.equal(manifest.host_permissions, undefined);
  assert.equal(manifest.content_scripts, undefined);
  const f = setup();
  const { windows } = await f.command('Partyline.windows');
  assert.deepEqual(windows[0].tabs.map(t => t.id), [1]);
  assert.equal(windows[0].focused, true);
  assert.equal(windows[0].tabs[0].active, true);
  assert.equal(f.calls.length, 0);
});

test('commands, iframe flat sessions, auto attach, crash and detach events', async () => {
  const f = setup(), session = await f.attach();
  await f.command('Target.setAutoAttach', { autoAttach: true, flatten: true }, session);
  assert.deepEqual(f.calls.at(-1)[2].filter, [{ type: 'iframe', exclude: false }, { exclude: true }]);
  f.api.debugger.onEvent.fire({ tabId: 1 }, 'Target.attachedToTarget', { sessionId: 'child', targetInfo: { type: 'iframe', url: 'https://frame.example.test/' } });
  await f.command('DOM.enable', {}, 'child');
  assert.deepEqual(f.calls.at(-1)[1], { tabId: 1, sessionId: 'child' });
  f.api.debugger.onEvent.fire({ tabId: 1, sessionId: 'child' }, 'Inspector.targetCrashed', {});
  assert.equal(f.messages.at(-1).sessionId, 'child');
  f.api.debugger.onEvent.fire({ tabId: 1 }, 'Target.attachedToTarget', { sessionId: 'worker', targetInfo: { type: 'worker' } });
  await assert.rejects(f.command('Runtime.enable', {}, 'worker'));
  f.api.debugger.onEvent.fire({ tabId: 1 }, 'Target.detachedFromTarget', { sessionId: 'child' });
  await assert.rejects(f.command('DOM.enable', {}, 'child'));
  const detaches = f.calls.filter(c => c[0] === 'detach').length;
  f.api.debugger.onDetach.fire({ tabId: 1 }, 'canceled_by_user');
  assert.equal(f.calls.filter(c => c[0] === 'detach').length, detaches);
  assert.equal(f.messages.at(-1).method, 'Inspector.detached');
  await assert.rejects(f.command('DOM.enable', {}, session));
});

test('demand, long operation, burst reuse and fake-clock idle latency', async () => {
  const f = setup();
  await f.command('Partyline.begin');
  const session = await f.attach();
  f.clock.advance(10000);
  assert.equal(f.calls.filter(c => c[0] === 'detach').length, 0);
  await f.command('DOM.enable', {}, session);
  await f.command('Partyline.end');
  f.clock.advance(IDLE_LINGER_MS - 1);
  await f.command('DOM.getDocument', {}, session);
  assert.equal(f.calls.filter(c => c[0] === 'attach').length, 1);
  f.clock.advance(IDLE_LINGER_MS);
  await Promise.resolve();
  assert.equal(f.calls.filter(c => c[0] === 'detach').length, 1);
  assert.deepEqual(await f.command('Partyline.metrics'), { attach_ms: [7], detach_ms: [3] });
  assert.deepEqual(await f.command('Partyline.resume', { sessionId: session }), { reattached: true, documentChanged: false });
  await f.command('Partyline.end');
  f.clock.advance(IDLE_LINGER_MS); await Promise.resolve();
  f.api.loader = 'document-2';
  assert.equal((await f.command('Partyline.resume', { sessionId: session })).documentChanged, true);
});

test('revoke gates synchronously and starts detach before acknowledgment', async () => {
  const f = setup(), session = await f.attach();
  let finish;
  f.api.debugger.detach = d => { f.calls.push(['detach', d]); return new Promise(r => { finish = r; }); };
  const revoke = f.command('Partyline.revoke');
  assert.equal(f.calls.at(-1)[0], 'detach');
  await assert.rejects(f.command('Input.dispatchMouseEvent', {}, session));
  const count = f.messages.length;
  f.api.debugger.onEvent.fire({ tabId: 1 }, 'DOM.documentUpdated', {});
  assert.equal(f.messages.length, count);
  finish(); await revoke;
});

test('revoke during attachment detaches the late success', async () => {
  const f = setup(); let finish;
  f.api.debugger.attach = () => new Promise(r => { finish = r; });
  await f.command('Partyline.scope', { tabs: [1] });
  const attach = f.command('Target.attachToTarget', { targetId: '1' });
  while (!finish) await Promise.resolve();
  await f.command('Partyline.revoke'); finish();
  await assert.rejects(attach);
  assert.equal(f.calls.at(-1)[0], 'detach');
});

test('refuse ungranted/restricted tabs, cross grant roots and browser escape commands', async () => {
  const f = setup();
  await assert.rejects(f.command('Target.attachToTarget', { targetId: '1' }));
  await f.command('Partyline.scope', { tabs: [2] });
  await assert.rejects(f.command('Target.attachToTarget', { targetId: '2' }));
  for (const url of ['chrome-extension://id/', 'devtools://devtools/', 'about:blank', 'javascript:alert(1)']) {
    f.tabs.get(2).url = url;
    await assert.rejects(f.command('Target.attachToTarget', { targetId: '2' }));
  }
  const session = await f.attach();
  for (const method of ['Browser.close', 'Target.createTarget', 'Target.attachToTarget']) {
    await assert.rejects(f.command(method, { targetId: '2' }, session));
  }
  await assert.rejects(f.command('Target.detachFromTarget', { sessionId: 'unrelated' }, session));
  await f.relay.command({ method: 'Partyline.scope', grant: 'other', params: { tabs: [1], windowId: 9 } });
  await assert.rejects(f.relay.command({ method: 'Target.attachToTarget', grant: 'other', params: { targetId: '1' } }));
  f.tabs.get(1).pendingUrl = 'chrome://settings';
  await assert.rejects(f.command('Input.dispatchKeyEvent', {}, session));
  f.tabs.get(1).pendingUrl = undefined;
  f.api.tabs.onUpdated.fire(1, { url: 'chrome://settings' });
  await assert.rejects(f.command('DOM.enable', {}, session));
});

test('tab movement, removal, and idle detach completion gate subsequent dispatch', async () => {
  const f = setup(), session = await f.attach();
  f.tabs.get(1).windowId = 10;
  await assert.rejects(f.command('Input.dispatchKeyEvent', {}, session));
  f.tabs.get(1).windowId = 9;
  f.api.tabs.onAttached.fire(1, { newWindowId: 10 });
  await assert.rejects(f.command('DOM.enable', {}, session));
  await f.attach();
  f.api.tabs.onRemoved.fire(1);
  await assert.rejects(f.command('DOM.enable', {}, session));
  const current = await f.attach();
  let finish;
  f.api.debugger.detach = () => new Promise(r => { finish = r; });
  f.clock.advance(IDLE_LINGER_MS);
  const resume = f.command('Partyline.resume', { sessionId: current });
  await Promise.resolve();
  assert.equal(f.calls.filter(c => c[0] === 'attach').length, 3);
  finish(); await resume;
  assert.equal(f.calls.filter(c => c[0] === 'attach').length, 4);
});

test('native dispatch envelopes and error replies', async () => {
  const f = setup();
  await f.relay.receive({ id: 1, method: 'Partyline.dispatch', params: { method: 'Partyline.scope', grant: 'g', params: { tabs: [1], windowId: 9 } } });
  assert.deepEqual(f.messages.at(-1), { id: 1, result: {} });
  await f.relay.receive({ id: 2, method: 'Target.attachToTarget', grant: 'bad', params: { targetId: '1' } });
  assert.ok(f.messages.at(-1).error);
  await f.command('Partyline.reset');
  await assert.rejects(f.command('Partyline.scope', { tabs: ['1'] }));
});

test('report measured JS dispatch overhead separately from modeled Chrome latency', async t => {
  const f = setup();
  let attach = 0, detach = 0;
  for (let i = 0; i < 100; i++) {
    let start = performance.now();
    const session = await f.attach();
    attach += performance.now() - start;
    start = performance.now();
    await f.command('Target.detachFromTarget', { sessionId: session });
    detach += performance.now() - start;
  }
  t.diagnostic(`100 fake cycles: attach ${(attach / 100).toFixed(4)} ms/call, detach ${(detach / 100).toFixed(4)} ms/call; injected Chrome latency 7 ms attach, 3 ms detach`);
});

test('a failed native-port publish cannot prevent revoke detach', async () => {
  const f = fixture();
  const relay = new Relay(f.api, () => { throw Error('Native port closed'); }, f.clock);
  await relay.command({ method: 'Partyline.scope', grant: 'g', params: { tabs: [1], windowId: 9 } });
  await relay.command({ method: 'Target.attachToTarget', grant: 'g', params: { targetId: '1' } });
  await relay.command({ method: 'Partyline.revoke', grant: 'g' });
  assert.equal(f.calls.at(-1)[0], 'detach');
  assert.equal(relay.attachments.entries.size, 0);
});

test('failed idle detach retains ownership so revoke can retry cleanup', async () => {
  const f = setup();
  await f.attach();
  const original = f.api.debugger.detach;
  f.api.debugger.detach = async () => { throw Error('Interrupted'); };
  f.clock.advance(IDLE_LINGER_MS);
  for (let i = 0; i < 5; i++) await Promise.resolve();
  assert.equal([...f.relay.attachments.entries.values()][0].attached, true);
  f.api.debugger.detach = original;
  await f.command('Partyline.revoke');
  assert.equal(f.calls.at(-1)[0], 'detach');
});

test('failed revoke detach remains gated and is retried on reset', async () => {
  const f = setup(), session = await f.attach();
  const original = f.api.debugger.detach;
  f.api.debugger.detach = async () => { throw Error('Interrupted'); };
  await f.command('Partyline.revoke');
  assert.equal(f.relay.attachments.orphans.size, 1);
  await assert.rejects(f.command('DOM.enable', {}, session));
  await f.command('Partyline.scope', { tabs: [1] });
  await assert.rejects(f.command('Target.attachToTarget', { targetId: '1' }));
  f.api.debugger.detach = original;
  await f.command('Partyline.reset');
  assert.equal(f.relay.attachments.orphans.size, 0);
  assert.equal(f.calls.at(-1)[0], 'detach');
});

test('Chrome Cancel revokes the grant, blocks repeated scopes and permits only a new share', async () => {
  const f = setup(), session = await f.attach();
  f.api.debugger.onDetach.fire({ tabId: 1 }, 'canceled_by_user');
  assert.ok(f.messages.some(m => m.method === 'Partyline.grantCancelled' && m.params.grant === 'g'));
  await assert.rejects(f.command('DOM.enable', {}, session));
  await assert.rejects(f.command('Target.attachToTarget', { targetId: '1' }));
  await assert.rejects(f.command('Partyline.scope', { tabs: [1] }));
  await f.command('Partyline.reset');
  await assert.rejects(f.command('Partyline.scope', { tabs: [1] }));
  await f.relay.command({ method: 'Partyline.scope', grant: 'fresh-share', params: { tabs: [1], windowId: 9 } });
  const result = await f.relay.command({ method: 'Target.attachToTarget', grant: 'fresh-share', params: { targetId: '1' } });
  assert.ok(result.sessionId.startsWith('fresh-share:1:'));
});

test('local file pages and unsafe iframe sessions cannot enter the granted capability', async () => {
  const f = setup(), session = await f.attach();
  for (const url of ['file:///secret', 'chrome://settings', 'chrome-extension://id/']) {
    await assert.rejects(f.command('Page.navigate', { url }, session));
    f.api.debugger.onEvent.fire({ tabId: 1 }, 'Target.attachedToTarget',
      { sessionId: 'unsafe', targetInfo: { type: 'iframe', url } });
    await assert.rejects(f.command('DOM.enable', {}, 'unsafe'));
  }
  f.tabs.get(1).url = 'file:///secret';
  await assert.rejects(f.command('DOM.enable', {}, session));
});

test('replacement page sessions stay alive when recovery closes the old session', async () => {
  const f = setup(), old = await f.attach();
  const fresh = (await f.command('Target.attachToTarget', { targetId: '1' })).sessionId;
  assert.notEqual(old, fresh);
  await assert.rejects(f.command('Target.detachFromTarget', { sessionId: old }));
  await f.command('DOM.enable', {}, fresh);
  assert.equal(f.calls.at(-1)[0], 'DOM.enable');
  assert.equal(f.calls.filter(c => c[0] === 'attach').length, 2);
});
