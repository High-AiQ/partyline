/**
 * A coarse shared clock so relative day labels ("Today" → "Yesterday") roll
 * over without a reload. Only `Feed` runs it, and only while mounted.
 */

export const CLOCK_TICK_MS = 60_000;

class Clock {
  now = $state(new Date());

  /** Re-read the time every minute; the returned function stops the ticking. */
  run(): () => void {
    this.now = new Date();
    const timer = setInterval(() => {
      this.now = new Date();
    }, CLOCK_TICK_MS);
    return () => {
      clearInterval(timer);
    };
  }
}

export const clock = new Clock();
