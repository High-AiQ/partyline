import { MicReadout } from "./mic-readout.svelte";
import type { MicHooks } from "../lib/voice-recorder";

export class WalkthroughMic extends MicReadout {
  private sawInput = false;
  private sawSilence = false;

  readonly takeHooks: Required<MicHooks> = {
    ...this.hooks,
    onlevel: (level) => {
      this.hooks.onlevel(level);
      if (level >= 0.018) this.sawInput = true;
    },
    onsilent: (silent) => {
      this.hooks.onsilent(silent);
      if (silent) this.sawSilence = true;
    },
  };

  get noInput(): boolean {
    return this.sawSilence && !this.sawInput;
  }

  resetTake(): void {
    this.sawInput = false;
    this.sawSilence = false;
    this.reset();
  }
}
