import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture, event } from './fakes.test.js';

const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };

test('self disconnect cleanup, toolbar recovery and bounded automatic reconnect match Chrome', async () => {
  const f = fixture(), ports = [];
  f.api.runtime = { onStartup: event(), onInstalled: event(), lastError: null,
    connectNative(name) {
      assert.equal(name, 'io.partyline.chrome');
      const port = { onMessage: event(), onDisconnect: event(), sent: [], disconnected: false,
        postMessage(m) { this.sent.push(m); },
        disconnect() { this.disconnected = true; }, // no onDisconnect on the calling port
        remoteDisconnect() { this.disconnected = true; this.onDisconnect.fire(); } };
      ports.push(port); return port;
    } };
  f.api.action = { onClicked: event() };
  globalThis.chrome = f.api;
  await import('./worker.js'); await flush();
  assert.equal(ports.length, 1);
  f.api.runtime.onStartup.fire(); await flush();
  assert.equal(ports.length, 1);
  const attach = async port => {
    port.onMessage.fire({ id: 1, method: 'Partyline.scope', grant: 'g', params: { tabs: [1], windowId: 9 } });
    port.onMessage.fire({ id: 2, method: 'Partyline.begin', grant: 'g' });
    port.onMessage.fire({ id: 3, method: 'Target.attachToTarget', grant: 'g', params: { targetId: '1' } });
    await flush();
  };
  await attach(ports[0]);
  ports[0].onMessage.fire({ chunk: { index: 9, total: 2, data: '' } });
  assert.equal(ports[0].disconnected, true);
  assert.equal(f.calls.filter(c => c[0] === 'detach').length, 1);
  f.api.action.onClicked.fire(); await flush();
  assert.equal(ports.length, 2);
  await attach(ports[1]);
  ports[1].onMessage.fire({ method: 'Partyline.suspend' });
  assert.equal(ports[1].disconnected, true);
  assert.equal(f.calls.filter(c => c[0] === 'detach').length, 2);
  await flush(); assert.equal(ports.length, 2);
  f.api.action.onClicked.fire(); await flush();
  assert.equal(ports.length, 3);
  // Receiving hello must not replenish the automatic retry budget.
  ports[2].onMessage.fire({ method: 'Partyline.hello' });
  ports[2].remoteDisconnect(); await flush();
  assert.equal(ports.length, 4);
  ports[3].onMessage.fire({ method: 'Partyline.hello' });
  ports[3].remoteDisconnect(); await flush();
  assert.equal(ports.length, 4);
  f.api.action.onClicked.fire(); await flush();
  assert.equal(ports.length, 5);
  ports[4].remoteDisconnect(); await flush(); // absent host has no hello, so no retry
  assert.equal(ports.length, 5);
  delete globalThis.chrome;
});
