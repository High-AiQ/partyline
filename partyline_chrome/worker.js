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
      if (message?.method === 'Partyline.suspend') disconnect();
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
