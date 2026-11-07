/**
 * The speech recognizers the composer's mic offers, kept fresh.
 *
 * Loaded on demand, again on every socket handshake (a restart may have
 * added presets) and on `asr_presets_changed` (someone edited them in
 * settings). A failed load is never silent: `error` says why, and a retry is
 * scheduled with backoff until one succeeds.
 *
 * Which recognizer this browser's mic uses is chosen in Settings → Voice and
 * remembered per browser; `active` falls back to the server default when the
 * choice is gone or unavailable.
 */
import { choosePreset, clearSavedPreset, readSavedPreset, savePreset } from "../lib/voice";
import { voiceApi } from "../lib/voice-api";
import type { VoiceListing } from "../lib/voice-api";

export const RETRY_BASE_MS = 1000;
export const RETRY_MAX_MS = 60_000;

export function retryDelay(attempt: number): number {
  return Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** Math.max(0, attempt));
}

export class VoicePresets {
  listing = $state<VoiceListing | null>(null);
  error = $state<string | null>(null);
  loading = $state(false);
  /** This browser's pick; null follows the server default. */
  chosen = $state<string | null>(readSavedPreset());
  /**
   * Bumped when the list may have changed somewhere else: a refresh (reconnect
   * or `asr_presets_changed`) or a load that recovers after a failure. The
   * settings tab refetches its own listing on it.
   */
  revision = $state(0);
  #attempt = 0;
  #generation = 0;
  /** Set once a mic or the settings tab has asked; until then a handshake or event loads nothing. */
  #wanted = false;
  #timer: ReturnType<typeof setTimeout> | null = null;

  /** Fetch now; the newest call wins, and any pending retry is replaced. */
  async load(): Promise<void> {
    this.#clearRetry();
    const generation = ++this.#generation;
    this.loading = true;
    try {
      const listing = await voiceApi.presets();
      if (generation !== this.#generation) return;
      this.listing = listing;
      this.error = null;
      if (this.#attempt > 0) this.revision++;
      this.#attempt = 0;
    } catch (failure: unknown) {
      if (generation !== this.#generation) return;
      this.error = failure instanceof Error ? failure.message : "could not load speech recognizers";
      this.#timer = setTimeout(() => void this.load(), retryDelay(this.#attempt++));
    } finally {
      if (generation === this.#generation) this.loading = false;
    }
  }

  /** The preset the mic will use: the remembered pick if it works, else the default, else any that works. */
  get active(): string | null {
    const listing = this.listing;
    return listing ? choosePreset(listing.presets, this.chosen, listing.default) : null;
  }

  choose(name: string | null): void {
    this.chosen = name;
    if (name) savePreset(name);
    else clearSavedPreset();
  }

  /** A take was refused with 503: mark that one preset down until the next load. */
  markUnavailable(name: string, reason: string): void {
    const listing = this.listing;
    if (!listing) return;
    this.listing = {
      ...listing,
      presets: listing.presets.map((entry) =>
        entry.name === name ? { ...entry, available: false, reason } : entry,
      ),
    };
  }

  /** Load once if nothing has been loaded or is on its way. */
  ensure(): void {
    this.#wanted = true;
    if (!this.listing && !this.loading && this.#timer === null) void this.load();
  }

  /** A reconnect or `asr_presets_changed`: refetch, if anything here has ever wanted the list. */
  refresh(): void {
    if (!this.#wanted) return;
    this.revision++;
    void this.load();
  }

  reset(): void {
    this.#wanted = false;
    this.#clearRetry();
    this.#generation++;
    this.#attempt = 0;
    this.listing = null;
    this.error = null;
    this.loading = false;
  }

  #clearRetry(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }
}

export const voicePresets = new VoicePresets();
