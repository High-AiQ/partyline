/** The owner-scoped computer list is supplied by the chat socket. */
import type { ScreenDevice } from "../lib/screen-api";
import { screenStatus } from "./screen-status.svelte.js";

export function useScreenDevices(): { readonly list: ScreenDevice[] } {
  return {
    get list() {
      return screenStatus.devices;
    },
  };
}
