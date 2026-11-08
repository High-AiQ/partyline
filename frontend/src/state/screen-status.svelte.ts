/** A helper connection change invalidates the open computer list. */
class ScreenStatus {
  revision = $state(0);
  openPicker = $state(0);
}

export const screenStatus = new ScreenStatus();
