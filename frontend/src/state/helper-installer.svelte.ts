import { screenApi, type HelperInstaller } from "../lib/screen-api";

/** The exact-version Windows installer link, asked of the server once; the web UI never builds the URL itself. */
class HelperInstallerState {
  info = $state<HelperInstaller | null>(null);
  private pending: Promise<void> | null = null;

  /** Loads the link on first use; a failed load is retried by the next caller. */
  ensure(): Promise<void> {
    if (this.info) return Promise.resolve();
    this.pending ??= screenApi
      .installer()
      .then((info) => {
        this.info = info;
      })
      .catch(() => undefined)
      .finally(() => {
        this.pending = null;
      });
    return this.pending;
  }
}

export const helperInstaller = new HelperInstallerState();
