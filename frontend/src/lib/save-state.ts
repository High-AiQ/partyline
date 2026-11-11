/** A small save lifecycle for settings: idle → saving → saved (briefly) or error. */

export type SavePhase = "idle" | "saving" | "saved" | "error";
export const SAVED_FLASH_MS = 2000;

export interface SaveSnapshot {
  phase: SavePhase;
  message: string;
}

/** Runs one save at a time and reports each phase; "saved" fades back to idle on a timer. */
export class SaveTracker {
  #timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly report: (state: SaveSnapshot) => void) {}

  async run<T>(work: () => Promise<T>, fallback = "could not save"): Promise<T | undefined> {
    this.#clear();
    this.report({ phase: "saving", message: "" });
    try {
      const result = await work();
      this.report({ phase: "saved", message: "" });
      // no-poll (b): one-shot UI deadline; no state request
      this.#timer = setTimeout(() => {
        this.#timer = null;
        this.report({ phase: "idle", message: "" });
      }, SAVED_FLASH_MS);
      return result;
    } catch (failure: unknown) {
      this.report({ phase: "error", message: failure instanceof Error ? failure.message : fallback });
      return undefined;
    }
  }

  dispose(): void {
    this.#clear();
  }

  #clear(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }
}
