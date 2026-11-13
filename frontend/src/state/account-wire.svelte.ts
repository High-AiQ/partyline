/** Keep the existing authenticated wire alive on the home page as an account view. */
import type { WireIdentity } from "../lib/wire-commands";
import type { HelloEvent } from "../lib/contracts";
import { screenStatus } from "./screen-status.svelte.js";
import { room } from "./room.svelte.js";
import { session } from "./session.svelte.js";
import { voicePresets } from "./voice-presets.svelte.js";
import { resources } from "./resources.svelte.js";
import { restart } from "./restart.svelte.js";
import { wire } from "./wire.svelte.js";

export function connectAccountWire(identity: WireIdentity, handshake: (hello: HelloEvent) => void): void {
  wire.connect(
    "~account",
    identity,
    (event) => {
      if (event.type === "screen_snapshot") {
        screenStatus.indicators = event.indicators;
        screenStatus.devices = event.devices;
      } else if (event.type === "asr_presets_changed") {
        voicePresets.receive(event.settings);
      } else if (event.type === "resources") {
        resources.snapshot = event.snapshot;
      } else if (event.type === "restart_request") {
        // Broadcast to every wire, this one included: no line has to be open to decide it.
        restart.apply(event.request);
      }
    },
    () => undefined,
    handshake,
  );
}

export function useAccountWire(): void {
  $effect(() => {
    if (session.signedIn && !room.conversation) {
      connectAccountWire(room.identity, (hello) => {
        session.acceptHandshake(hello.version, hello.instance_name, hello.handle);
      });
    }
  });
}
