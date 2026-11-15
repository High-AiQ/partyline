// The bounded schedule for reconnecting the native port, driven by chrome.alarms and browser events.
//
// no-poll (e): this is reconnect-after-transport-failure, not state polling. An attempt is made only after
// a disconnect (immediately, then after 1 s, 5 s, 30 s, 2 min and 5 min), by one alarm at a time, and
// every success (a hello) or toolbar click ends it. After the last step it stops: only a click, a browser
// start or a tab activation (at most once every MIN_GAP seconds) tries again. Nothing runs on an interval.
export const DELAYS = [0, 1, 5, 30, 120, 300]; // seconds before the next attempt, by failures so far
export const MIN_GAP = 30;
export const ALARM = 'partyline-reconnect';
const KEY = 'reconnect';

export class Backoff {
  // `store` survives the service worker being stopped between alarms (cleared when the extension reloads).
  constructor(api, now = () => Date.now()) {
    this.api = api;
    this.now = now;
    this.failures = 0;
    this.last = 0;
    this.ready = (async () => {
      try {
        const saved = (await api.storage?.session?.get(KEY))?.[KEY];
        if (saved && Number.isInteger(saved.failures)) ({ failures: this.failures, last: this.last } = saved);
      } catch { /* in memory only */ }
    })();
  }

  save() {
    try {
      Promise.resolve(this.api.storage?.session?.set({ [KEY]: { failures: this.failures, last: this.last } })).catch(() => {});
    } catch { /* in memory only */ }
  }

  async reset() {
    await this.ready;
    this.failures = 0;
    this.save();
    await this.cancel();
  }

  async cancel() {
    try { await this.api.alarms?.clear(ALARM); } catch { /* no alarms */ }
  }

  // An attempt starts now.
  async began() {
    await this.ready;
    this.last = this.now();
    this.save();
  }

  // An attempt failed: the seconds until the next one (0: at once), or null when the schedule is spent.
  // `quiet` skips the immediate try, for a failure that is unlikely to clear by itself within a second.
  async failed(quiet = false) {
    await this.ready;
    let delay = DELAYS[this.failures++];
    if (delay === 0 && quiet) delay = DELAYS[this.failures++];
    this.failures = Math.min(this.failures, DELAYS.length);
    this.save();
    if (delay === undefined) return null;
    if (delay > 0) await this.schedule(delay);
    return delay;
  }

  async schedule(seconds) {
    try { await this.api.alarms.create(ALARM, { when: this.now() + seconds * 1000 }); } catch { /* no alarms */ }
  }

  // A browser event (tab activation) may retry only when no alarm is waiting and the last try is not recent.
  async mayRetry() {
    await this.ready;
    if (this.now() - this.last < MIN_GAP * 1000) return false;
    try { return !(await this.api.alarms?.get(ALARM)); } catch { return true; }
  }
}
