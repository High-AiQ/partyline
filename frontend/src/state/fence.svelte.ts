/** Persistent boot-time write-fence status shared across lines and reconnects. */
import type { FenceStatus } from "../lib/fence-contracts";
import { fenceApi } from "../lib/fence-api";

class FenceState {
  status = $state<FenceStatus | null>(null);
  #loading: Promise<void> | null = null;
  #loaded = false;

  load(refresh = false): Promise<void> {
    if (this.#loading) return this.#loading;
    if (this.#loaded && !refresh) return Promise.resolve();
    const pending = fenceApi
      .status()
      .then((status) => {
        this.status = status;
        this.#loaded = true;
      })
      .finally(() => {
        if (this.#loading === pending) this.#loading = null;
      });
    this.#loading = pending;
    return pending;
  }
}

export const fence = new FenceState();
