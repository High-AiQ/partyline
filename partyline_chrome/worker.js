import { Relay } from './relay.js';
import { Status, explain } from './status.js';
import { Decoder, packets } from './wire.js';

// Only states, versions and Chrome's own error text are logged: never page content or CDP payloads.
const log = { info: (...a) => console.info('[Partyline]', ...a), warn: (...a) => console.warn('[Partyline]', ...a) };
const status = new Status(chrome.action, log);
let current = null; // the live native port: { connection, greeted, disconnect }
let reconnects = 0;
let closing = Promise.resolve();
const relay = new Relay(chrome, message => {
  if (current) for (const packet of packets(message)) current.connection.postMessage(packet);
});
async function connect(resetBudget = false, why = 'startup', force = false) {
  if (resetBudget) reconnects = 0;
  await closing;
  if (current && force && !current.greeted) {
    log.warn(`${why}: the native port never greeted; reconnecting`);
    current.disconnect();
    await closing;
  }
  if (current) {
    log.info(`${why}: already connected to the native host`);
    status.refresh();
    return;
  }
  log.info(`${why}: connecting to the native host`);
  status.set('connecting');
  const connection = chrome.runtime.connectNative('io.partyline.chrome');
  const self = { connection, greeted: false, disconnect };
  current = self;
  const decoder = new Decoder();
  let received = false, ended = false;
  let hellos = Promise.resolve();
  function closed(remote = false, error = '') {
    if (ended) return;
    ended = true;
    if (current === self) current = null;
    closing = relay.attachments.reset().catch(() => {});
    if (!remote) return;
    const retry = received && reconnects < 1;
    log.warn(`native host disconnected${error ? `: ${error}` : ''}${retry ? '; retrying once' : ''}`);
    if (retry) {
      reconnects++;
      // no-poll (e): at most one automatic reconnect per startup or user gesture.
      void connect(false, 'automatic retry');
    } else status.set('error', explain(error || 'Native host has exited.'));
  }
  function disconnect() {
    closed(); // Chrome does not emit onDisconnect on the port calling disconnect().
    connection.disconnect();
  }
  async function hello(message) {
    self.greeted = true;
    // A new hello starts a new helper session: nothing attached before it (an update, a lock, a
    // reconnect) may collide with the grants that follow. The revoke gates run synchronously here.
    const dropped = relay.attachments.reset().catch(() => {});
    if (message.helper_connected === false) {
      log.info('native host is up; waiting for the helper to attach');
      status.set('waiting');
    } else {
      log.info(`helper ${message.helper_version || '(unknown version)'} attached`);
      status.set('connected', message.helper_version);
    }
    await dropped;
    const running = chrome.runtime.getManifest?.().version;
    if (!ended && await claimReload(chrome.storage.local, running, message) && !ended) {
      log.info(`reloading the extension: running ${running}, helper ships ${message.extension_version}`);
      disconnect();
      chrome.runtime.reload();
    } else if (shouldReload(running, message)) {
      log.info(`not reloading: a reload to ${message.extension_version} was already attempted`);
    }
  }
  connection.onMessage.addListener(packet => {
    if (ended) return;
    try {
      const message = decoder.accept(packet);
      if (message?.method === 'Partyline.hello') {
        received = true;
        hellos = hellos.then(() => hello(message)).catch(disconnect);
      } else if (message?.method === 'Partyline.suspend') {
        log.info('the helper paused the native host for an update');
        disconnect();
        status.set('paused');
      } else if (message) {
        received = true;
        if (message.method === 'Partyline.reset') {
          log.info('the helper detached');
          status.set('waiting');
        }
        void relay.receive(message);
      }
    } catch {
      log.warn('unreadable message from the native host; reconnecting needs a click');
      disconnect();
      status.set('error', 'received an unreadable message from the helper bridge. Click this button to reconnect');
    }
  });
  connection.onDisconnect.addListener(() => closed(true, chrome.runtime.lastError?.message || ''));
}
const start = why => () => { void connect(true, why); };
chrome.runtime.onStartup.addListener(start('browser startup'));
chrome.runtime.onInstalled.addListener(start('installed or updated'));
chrome.action.onClicked.addListener(() => {
  if (!current) status.set('connecting'); // the click is visible before the connect resolves
  void connect(true, 'toolbar click', true);
});
start('service worker start')();

// Reload restarts this service worker, whose startup path reconnects the native host itself.
export function shouldReload(running, hello) {
  const parse = value => typeof value === 'string' && /^\d{1,9}(\.\d{1,9}){0,3}$/.test(value)
    ? value.split('.').map(Number) : null;
  const before = parse(running), after = parse(hello.extension_version);
  if (hello.auto_update !== true || !before || !after) return false;
  for (let i = 0; i < 4; i++) {
    const a = before[i] || 0, b = after[i] || 0;
    if (a !== b) return b > a;
  }
  return false;
}

// Persist before reload: a failed reload or a differently loaded unpacked folder cannot restart a storm.
export async function claimReload(storage, running, hello) {
  if (!shouldReload(running, hello)) return false;
  const key = 'auto_update_reload_version';
  const previous = (await storage.get(key))[key];
  if (typeof previous === 'string' && /^\d{1,9}(\.\d{1,9}){0,3}$/.test(previous) &&
      !shouldReload(previous, hello)) return false;
  await storage.set({ [key]: hello.extension_version });
  return true;
}
