import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture } from './fakes.test.js';
import { Relay } from './relay.js';
import { CODES, chromeFailure, codeOf, refuse } from './refusal.js';

function setup() {
  const f = fixture();
  f.relay = new Relay(f.api, m => f.messages.push(m), f.clock);
  f.send = async (message, grant = 'g') => {
    f.messages.length = 0;
    await f.relay.receive({ id: 7, params: { windowId: 9 }, grant, ...message });
    return f.messages.find(m => m.id === 7);
  };
  f.scope = (grant, tabs = [1]) => f.relay.command({ method: 'Partyline.scope', params: { tabs, windowId: 9 }, grant });
  return f;
}
const code = reply => reply.error.code;

test('every refusal carries one fixed allowlisted code and never Chrome text', async () => {
  const f = setup();
  const secret = 'https://private.example/path';
  assert.equal(code(await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } })), 'tab_outside_grant');
  await f.scope('g');
  f.api.debugger.attach = async () => { throw Error(`cannot attach to ${secret}`); };
  const attach = await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } });
  assert.equal(code(attach), 'debugger_attach_failed');
  assert.ok(!JSON.stringify(attach).includes('private'));
  f.api.debugger.attach = async d => { f.calls.push(['attach', d]); };
  const session = (await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } })).result.sessionId;
  assert.equal(code(await f.send({ method: 'Page.navigate', params: { url: 'chrome://settings' }, sessionId: session })),
    'restricted_navigation');
  assert.equal(code(await f.send({ method: 'Browser.close', sessionId: session })), 'domain_refused');
  assert.equal(code(await f.send({ method: 'Target.detachFromTarget', params: { sessionId: 'x' }, sessionId: session })),
    'child_outside_grant');
  assert.equal(code(await f.send({ method: 'DOM.enable', sessionId: 'gone' })), 'revoked');
  f.api.debugger.sendCommand = async () => { throw Error(`failed on ${secret}`); };
  const failed = await f.send({ method: 'DOM.enable', sessionId: session });
  assert.equal(code(failed), 'debugger_command_failed');
  assert.ok(!JSON.stringify(failed).includes('private'));
  f.api.debugger.sendCommand = async () => { throw Error('Debugger is not attached to the tab'); };
  assert.equal(code(await f.send({ method: 'DOM.enable', sessionId: session })), 'debugger_detached');
  f.tabs.get(1).url = 'chrome://settings';
  assert.equal(code(await f.send({ method: 'DOM.enable', sessionId: session })), 'restricted_navigation');
  f.tabs.delete(1);
  assert.equal(code(await f.send({ method: 'DOM.enable', sessionId: session })), 'tab_outside_grant');
  assert.equal(code(await f.send({ method: 'Partyline.scope', params: { tabs: 'x' } })), 'tab_outside_grant');
  for (const reply of f.messages) assert.ok(!reply.error || CODES.includes(reply.error.code));
});

test('child detached, revoked and an unknown failure use their codes', async () => {
  const f = setup();
  await f.scope('g');
  const session = (await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } })).result.sessionId;
  f.api.debugger.onEvent.fire({ tabId: 1 }, 'Target.attachedToTarget', { sessionId: 'c', targetInfo: { type: 'iframe', url: 'https://f.example.test/' } });
  f.api.debugger.onEvent.fire({ tabId: 1 }, 'Target.detachedFromTarget', { sessionId: 'c' });
  assert.equal(code(await f.send({ method: 'DOM.enable', sessionId: 'c' })), 'revoked'); // unknown child session
  await f.relay.command({ method: 'Partyline.revoke', grant: 'g' });
  assert.equal(code(await f.send({ method: 'DOM.enable', sessionId: session })), 'revoked');
  assert.equal(codeOf(Error('anything')), 'debugger_command_failed');
  assert.equal(refuse('not-a-code').code, 'debugger_command_failed');
  assert.equal(chromeFailure(refuse('revoked'), 'x').code, 'revoked');
  assert.equal(chromeFailure(Error('whatever'), 'debugger_attach_failed').code, 'debugger_attach_failed');
});

test('a hold left by a grant from before an update never strands a new grant on the same tab', async () => {
  const f = setup();
  await f.scope('before-update');
  await f.relay.command({ method: 'Partyline.dispatch', params: { method: 'Partyline.begin', grant: 'before-update' } });
  await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'before-update');
  // The helper restarted and never revoked: the new grant is refused with its fixed code.
  await f.scope('after-update');
  assert.equal(code(await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'after-update')),
    'tab_owned_by_other_grant');
  // The helper's scoped release spares a live grant's tab and drops only the stale one.
  assert.deepEqual(await f.relay.command({ method: 'Partyline.release', params: { tabs: [1], live: ['before-update'] } }), { released: 0 });
  assert.deepEqual(await f.relay.command({ method: 'Partyline.release', params: { tabs: [1], live: ['after-update'] } }), { released: 1 });
  assert.equal(f.calls.filter(c => c[0] === 'detach').length, 1);
  const reply = await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'after-update');
  assert.ok(reply.result.sessionId.startsWith('after-update:1:'));
  assert.equal(code(await f.send({ method: 'Partyline.release', params: { tabs: ['1'], live: [] } })), 'tab_outside_grant');
});

test('a failed detach is retried by the next attach, and "not attached" counts as detached', async () => {
  const f = setup();
  await f.scope('old');
  await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'old');
  f.api.debugger.detach = async () => { throw Error('Detach failed'); };
  await f.relay.command({ method: 'Partyline.revoke', grant: 'old' });
  assert.equal(f.relay.attachments.orphans.size, 1);
  await f.scope('new');
  assert.equal(code(await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'new')),
    'previous_detach_incomplete');
  f.api.debugger.detach = async () => { throw Error('Debugger is not attached to the tab'); };
  assert.ok((await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'new')).result.sessionId);
  assert.equal(f.relay.attachments.orphans.size, 0);
});

test('a new hello drops every attachment and orphan from before it', async () => {
  const f = setup();
  await f.scope('old');
  await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'old');
  await f.relay.attachments.reset();
  await f.scope('new');
  assert.ok((await f.send({ method: 'Target.attachToTarget', params: { targetId: '1' } }, 'new')).result.sessionId);
});
