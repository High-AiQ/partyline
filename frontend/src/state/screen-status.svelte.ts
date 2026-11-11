import type { ScreenDevice, ShareIndicator } from "../lib/screen-api";

/** A helper connection change invalidates the open computer list. */
class ScreenStatus {
  revision = $state(0);
  devices = $state<ScreenDevice[]>([]);
  indicators = $state<ShareIndicator[]>([]);
  openPicker = $state(0);
}

export const screenStatus = new ScreenStatus();
