import { Relay } from './relay.js';
import { Backoff, ALARM, HELLO_ALARM, RELEASE_DELAY } from './backoff.js';
import { Status, explain, brief, recoverable } from './status.js';
import { Decoder, packets } from './wire.js';

// Only states, versions and Chrome's own error text are logged: never page content or CDP payloads.
const log = { info: (...a) => console.info('[Partyline]', ...a), warn: (...a) => console.warn('[Partyline]', ...a) };
const status = new Status(chrome.action, log);
let current = null; // the live native port: { connection, greeted, disconnect }
const backoff = new Backoff(chrome);
let closing = Promise.resolve();
const relay = new Relay(chrome, message => {
  if (current) for (const packet of packets(message)) current.connection.postMessage(packet);
});
// One attempt at a time: a startup, an alarm, a tab activation and a click may all arrive while the persisted
// schedule is still loading, and must not each open a native port.
let queue = Promise.resolve();
function connect(...args) {
  const run = queue.then(() => open(...args));
  queue = run.catch(() => {});
  return run;
}
async function open(resetBudget = false, why = 'startup', force = false) {
  if (resetBudget) await backoff.reset();
  await closing;
  if (current && force && (!current.greeted || status.state?.name !== 'connected')) {
    // A click while no helper is attached (or a port that never greeted) starts over with a new host.
    log.warn(`${why}: no helper is attached; reconnecting the native port`);
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
  await backoff.began();
  let connection;
  try {
    connection = chrome.runtime.connectNative('io.partyline.chrome');
  } catch (error) { // Chrome refused to open the port at all: still a failed attempt, never a stuck "connecting"
    log.warn(`could not open the native port: ${error?.message || error}`);
    void lost(String(error?.message || error));
    return;
  }
  const self = { connection, greeted: false, disconnect, silent };
  current = self;
  void backoff.awaitingHello();
  const decoder = new Decoder();
  let ended = false;
  let busy = false; // the host said an older host still holds the helper bridge
  let hellos = Promise.resolve();
  function closed(remote = false, error = '') {
    if (ended) return;
    ended = true;
    void backoff.helloSettled();
    if (current === self) current = null;
    closing = relay.attachments.reset().catch(() => {});
    if (!remote) return;
    log.warn(`native host disconnected${error ? `: ${error}` : ''}`);
    void lost(busy ? 'An older native host is still running.' : error || 'Native host has exited.');
  }
  // The port opened but no greeting came: end it like any other transport failure.
  function silent() {
    if (ended || self.greeted) return;
    log.warn('the native host never greeted; reconnecting');
    closed();
    connection.disconnect();
    void lost('Native host did not answer.');
  }
  function disconnect() {
    closed(); // Chrome does not emit onDisconnect on the port calling disconnect().
    connection.disconnect();
  }
  async function hello(message) {
    if (ended) return; // a hello queued behind a closed port must not repaint or reset the new one
    self.greeted = true;
    void backoff.helloSettled();
    // A new hello starts a new helper session: nothing attached before it (an update, a lock, a
    // reconnect) may collide with the grants that follow. The revoke gates run synchronously here.
    const dropped = relay.attachments.reset().catch(() => {});
    if (ended) return;
    if (message.helper_connected === false) {
      log.info('native host is up; waiting for the helper to attach');
      status.set('waiting');
    } else {
      log.info(`helper ${message.helper_version || '(unknown version)'} attached`);
      status.set('connected', message.helper_version);
    }
    void backoff.reset(); // a greeting ends the retries: the next loss starts the schedule again
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
        hellos = hellos.then(() => hello(message)).catch(disconnect);
      } else if (message?.method === 'Partyline.busy') {
        busy = true; // the host exits right after: Chrome's disconnect carries on through lost()
      } else if (message?.method === 'Partyline.suspend') {
        // The helper is away. The port stays up, so the next helper that attaches is greeted with no click;
        // only an installer that must free the host's files asks for `release`: the port closes and the
        // reconnect schedule starts after a delay (backoff.js).
        if (message.release === true) {
          // Reconnecting at once would make Chrome spawn the host mid-install: wait for one alarm instead.
          log.info(`the installer asked the native host to release its files; reconnecting in ${RELEASE_DELAY} s`);
          const armed = backoff.released();
          disconnect();
          status.set('updating');
          void armed;
        } else {
          log.info('the helper is away (paused); keeping the native port for its return');
          relay.attachments.reset().catch(() => {});
          status.set('waiting');
        }
      } else if (message) {
        if (message.method === 'Partyline.reset') {
          log.info('the helper is away; keeping the native port for its return');
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
// A port that closed on its own: reconnect by itself on the bounded schedule (backoff.js). The badge stays
// neutral while attempts remain, and goes red when they are spent. Only a registration or id mismatch is
// red at once, though the schedule still runs: a registration is briefly absent while an installer replaces it.
async function lost(error) {
  const fatal = !recoverable(error);
  status.set(...(fatal ? ['error', explain(error)] : ['reconnecting', brief(error)]));
  const delay = await backoff.failed(fatal);
  if (current) return; // a newer port (a click, an alarm) owns the badge now
  if (delay === null) {
    log.warn('giving up automatic reconnects; click the button, start Chrome again or switch tabs to retry');
    status.set('error', explain(error));
  } else if (delay === 0) void connect(false, 'automatic retry');
  else log.info(`retrying the native host in ${delay} s`);
}
const start = why => () => { void connect(true, why); };
chrome.runtime.onStartup.addListener(start('browser startup'));
chrome.runtime.onInstalled.addListener(start('installed or updated'));
chrome.action.onClicked.addListener(() => {
  if (!current) status.set('connecting'); // the click is visible before the connect resolves
  void connect(true, 'toolbar click', true);
});
chrome.alarms?.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM) void connect(false, 'retry alarm');
  else if (alarm.name === HELLO_ALARM && current) current.silent();
});
chrome.tabs?.onActivated?.addListener(async () => {
  if (!current && await backoff.mayRetry()) void connect(false, 'tab activation');
});
// A worker woken by an alarm, or started while the helper is still restarting, continues the schedule: it
// connects at once only when no alarm is pending and the schedule is not spent.
void backoff.mayStart().then(ok => ok ? connect(false, 'service worker start')
  : log.info('service worker start: the reconnect schedule decides when to try again'));

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
