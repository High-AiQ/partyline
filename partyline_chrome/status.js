// Toolbar feedback: the badge and title say whether the helper is reachable, and why not.
export const COLORS = { neutral: '#9aa0a6', connected: '#1e8e3e', error: '#d93025' };

// A failure that retrying cannot cure by itself: the registration or the extension id is wrong.
// Everything else (the host exited, closed, failed to start) is recoverable and retried on a bounded schedule.
export function recoverable(message) {
  const text = String(message || '').toLowerCase();
  return !text.includes('not found') && !text.includes('forbidden');
}

// The recoverable reason in a few words, for the title while the extension reconnects.
export function brief(message) {
  const text = String(message || '').toLowerCase();
  if (!text || text.includes('exited')) return 'the helper bridge stopped';
  if (text.includes('disconnected') || text.includes('closed')) return 'the helper bridge closed the connection';
  return `Chrome said: ${message}`;
}

// Chrome's lastError text, in plain words and with what to do about it.
export function explain(message) {
  const text = String(message || '').toLowerCase();
  if (text.includes('not found')) {
    return 'Chrome cannot find the Partyline native host. Reinstall or restart Partyline Helper to register it';
  }
  if (text.includes('forbidden')) {
    return 'Chrome refused the native host for this extension (extension id mismatch). '
      + 'Load the extension from the helper\'s own folder';
  }
  if (text.includes('has exited') || text.includes('exited')) {
    return 'The helper bridge stopped. Make sure Partyline Helper is running, then click this button';
  }
  if (text.includes('disconnected') || text.includes('closed')) {
    return 'The helper bridge closed the connection. Make sure Partyline Helper is running, then click this button';
  }
  return message ? `Could not reach the helper (${message}). Make sure Partyline Helper is running`
    : 'Could not reach the helper. Make sure Partyline Helper is running, then click this button';
}

const STATES = {
  connecting: () => ['…', 'neutral', 'Partyline: connecting to the helper…'],
  reconnecting: reason => ['…', 'neutral', `Partyline: reconnecting to the helper (${reason}); no click needed, or click to retry now`],
  waiting: () => ['…', 'neutral', 'Partyline: ready, waiting for Partyline Helper to attach (it connects by itself when it starts)'],
  connected: version => ['✓', 'connected', `Partyline: connected to helper ${version || ''}`.trim()],
  paused: () => ['!', 'error', 'Partyline: paused for a helper update. Click this button to reconnect'],
  error: reason => ['!', 'error', `Partyline: ${reason}`],
};

export class Status {
  constructor(action, log = console) {
    this.action = action;
    this.log = log;
    this.state = null;
  }

  set(name, detail) {
    const [text, color, title] = STATES[name](detail);
    this.state = { name, detail };
    const call = (method, value) => {
      try { Promise.resolve(this.action?.[method]?.(value)).catch(() => {}); } catch { /* no toolbar */ }
    };
    call('setBadgeText', { text });
    call('setBadgeBackgroundColor', { color: COLORS[color] });
    call('setTitle', { title });
  }

  refresh() {
    if (this.state) this.set(this.state.name, this.state.detail);
  }
}
