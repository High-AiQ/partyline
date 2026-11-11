/** Recognizer state arrives as socket snapshots; the browser remembers its own choice. */
import { choosePreset, clearSavedPreset, readSavedPreset, savePreset } from "../lib/voice";
import type { AsrSettings } from "../lib/asr-api";
import type { VoiceListing } from "../lib/voice-api";

export class VoicePresets {
  listing = $state<VoiceListing | null>(null);
  settings = $state<AsrSettings | null>(null);
  error = $state<string | null>(null);
  loading = $state(false);
  chosen = $state<string | null>(readSavedPreset());
  revision = $state(0);

  /** Socket snapshots replace the listing atomically, including after reconnect. */
  receive(settings: AsrSettings): void {
    this.settings = settings;
    this.listing = settings;
    this.error = null;
    this.loading = false;
    this.revision++;
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

  /** Subscribers wait for the socket's snapshot; mounting never fetches. */
  ensure(): void {
    this.loading = this.listing === null;
  }

  reset(): void {
    this.settings = null;
    this.listing = null;
    this.error = null;
    this.loading = false;
  }
}

export const voicePresets = new VoicePresets();
