import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";
import { installResourceAuthRecovery } from "./lib/resource-auth";
import { room } from "./state/room.svelte.js";
import { session } from "./state/session.svelte.js";
import { wire } from "./state/wire.svelte.js";
import { presence } from "./state/presence.svelte.js";

const root = document.getElementById("root");
if (!root) throw new Error("partyline requires a #root mount element");
// Images and media elements load tokened URLs inside the browser, where a
// 401 is invisible to application code. One capture-phase listener heals
// every such resource by refreshing and re-deriving its source once.
installResourceAuthRecovery();
const app = mount(App, { target: root });

/**
 * A deliberate handle for the browser tests in `tests/ui/`.
 *
 * Those tests need to drop a socket, deliver a fabricated server event, or read
 * whether the handshake completed — none of which can be reached from the DOM,
 * and all of which are genuinely part of the client/server protocol this app
 * implements. Exposing them on purpose, and documenting that they are a test
 * surface, is better than the tests reaching into a global that happened to
 * exist because the old page never used modules.
 */
if (typeof window !== "undefined") {
  window.partyline = { room, session, wire, presence };
}

export default app;
