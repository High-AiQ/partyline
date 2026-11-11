/** The computers paired to the open line, refetched whenever its screen status moves. Call during component init. */
import { screenApi, type ScreenDevice } from "../lib/screen-api";
import { room } from "./room.svelte.js";
import { screenStatus } from "./screen-status.svelte.js";

export function useScreenDevices(): { readonly list: ScreenDevice[] } {
  let devices = $state<ScreenDevice[]>([]);
  $effect(() => {
    const line = room.conversation?.id;
    void screenStatus.revision;
    if (!line) {
      devices = [];
      return;
    }
    void screenApi
      .devices(line)
      .then((result) => {
        if (room.conversation?.id === line) devices = result.devices;
      })
      .catch(() => {
        devices = [];
      });
  });
  return {
    get list() {
      return devices;
    },
  };
}
