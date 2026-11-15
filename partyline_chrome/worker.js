import { Relay } from './relay.js';
import { Decoder, packets } from './wire.js';

let port;
let reconnects = 0;
let closing = Promise.resolve();
const relay = new Relay(chrome, message => {
  if (port) for (const packet of packets(message)) port.postMessage(packet);
});
async function connect(resetBudget = false) {
  if (resetBudget) reconnects = 0;
  await closing;
  if (port) return;
  const connection = chrome.runtime.connectNative('io.partyline.chrome');
  port = connection;
  const decoder = new Decoder();
  let received = false, ended = false;
  let hellos = Promise.resolve();
  function closed(retry = false) {
    if (ended) return;
    ended = true;
    if (port === connection) port = null;
    closing = relay.attachments.reset().catch(() => {});
    if (retry && received && reconnects < 1) {
      reconnects++;
      // no-poll (e): at most one automatic reconnect per startup or user gesture.
      void connect();
    }
  }
  function disconnect() {
    closed(); // Chrome does not emit onDisconnect on the port calling disconnect().
    connection.disconnect();
  }
  connection.onMessage.addListener(packet => {
    if (ended) return;
    try {
      const message = decoder.accept(packet);
      if (message?.method === 'Partyline.hello') {
        received = true;
        hellos = hellos.then(async () => {
          if (!ended && await claimReload(chrome.storage.local, chrome.runtime.getManifest?.().version, message)
              && !ended) {
            disconnect();
            chrome.runtime.reload();
          }
        }).catch(disconnect);
      } else if (message?.method === 'Partyline.suspend') disconnect();
      else if (message) { received = true; void relay.receive(message); }
    } catch { disconnect(); }
  });
  connection.onDisconnect.addListener(() => {
    void chrome.runtime.lastError;
    closed(true);
  });
}
const start = () => { void connect(true); };
chrome.runtime.onStartup.addListener(start);
chrome.runtime.onInstalled.addListener(start);
chrome.action.onClicked.addListener(start);
start();

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
