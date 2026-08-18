/**
 * `window.partyline` is a deliberate test surface, not an accident.
 *
 * The browser tests in `tests/ui/` need to drop a socket, deliver a fabricated
 * server event, and read whether the handshake completed — none of which is
 * reachable from the DOM, and all of which are genuinely part of the
 * client/server protocol this app implements. Declaring it here means the
 * checker knows about it too, rather than every use needing a cast.
 */
declare global {
  /** Injected by Vite for production builds; blank under `npm run dev`. */
  const __PARTYLINE_BUILD__: string;

  interface Window {
    partyline: {
      room: typeof import("./state/room.svelte.js").room;
      session: typeof import("./state/session.svelte.js").session;
      wire: typeof import("./state/wire.svelte.js").wire;
      presence: typeof import("./state/presence.svelte.js").presence;
    };
  }
}

export {};
