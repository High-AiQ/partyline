/** What a screen shows about the live mic: its level, its name, a silence hint, a fallback notice. */
import type { MicHooks } from "../lib/voice-recorder";

export class MicReadout {
  level = $state(0);
  silent = $state(false);
  label = $state<string | null>(null);
  notice = $state<string | null>(null);

  /** Spread into a recorder's hooks. */
  readonly hooks: Required<MicHooks> = {
    onlevel: (level) => {
      this.level = level;
    },
    onsilent: (silent) => {
      this.silent = silent;
    },
    onmic: (label) => {
      this.label = label;
    },
    onnotice: (message) => {
      this.notice = message;
    },
  };

  /** The meter is off: bar empty, no hint. The label and notice stay until the next take. */
  quiet(): void {
    this.level = 0;
    this.silent = false;
  }

  reset(): void {
    this.quiet();
    this.label = null;
    this.notice = null;
  }
}
