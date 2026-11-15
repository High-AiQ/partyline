import test from 'node:test';
import assert from 'node:assert/strict';
import { Status, explain, COLORS } from './status.js';
import { event } from './fakes.test.js';

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function action() {
  const calls = {};
  return { calls, setBadgeText: ({ text }) => { calls.text = text; },
    setBadgeBackgroundColor: ({ color }) => { calls.color = color; },
    setTitle: ({ title }) => { calls.title = title; }, onClicked: event() };
}

test('each badge state sets text, colour and a plain-words title', () => {
  const a = action(), status = new Status(a);
  status.set('connecting');
  assert.deepEqual([a.calls.text, a.calls.color], ['…', COLORS.neutral]);
  assert.match(a.calls.title, /connecting/);
  status.set('waiting');
  assert.equal(a.calls.color, COLORS.neutral);
  assert.match(a.calls.title, /waiting for Partyline Helper/);
  status.set('connected', '1.6.2');
  assert.deepEqual([a.calls.text, a.calls.color], ['✓', COLORS.connected]);
  assert.equal(a.calls.title, 'Partyline: connected to helper 1.6.2');
  status.set('paused');
  assert.deepEqual([a.calls.text, a.calls.color], ['!', COLORS.error]);
  assert.match(a.calls.title, /Click this button/);
  status.set('error', explain('Specified native messaging host not found.'));
  assert.deepEqual([a.calls.text, a.calls.color], ['!', COLORS.error]);
  a.calls.title = '';
  status.refresh();
  assert.match(a.calls.title, /native host/);
});

test("Chrome's native messaging errors map to what the person must do", () => {
  assert.match(explain('Specified native messaging host not found.'), /Reinstall or restart Partyline Helper/);
  assert.match(explain('Access to the specified native messaging host is forbidden.'), /extension id mismatch/);
  assert.match(explain('Native host has exited.'), /helper bridge stopped.*Partyline Helper is running/);
  assert.match(explain('Error when communicating with the native messaging host.'),
    /Could not reach the helper \(Error when communicating/);
  assert.match(explain(''), /Make sure Partyline Helper is running/);
});

test('a toolbar without the action api, or one that throws, never breaks the worker', async () => {
  new Status(undefined).set('connected', '1');
  const throwing = { setBadgeText() { throw Error('no'); }, setBadgeBackgroundColor: async () => { throw Error('no'); },
    setTitle: () => Promise.reject(Error('no')) };
  new Status(throwing).set('error', 'x');
  await flush();
});
