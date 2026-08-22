/** Global recovery for authenticated resource URLs that stopped authorizing.
 *
 * REST, WebSocket, and blob downloads all detect 401 and refresh through
 * `http.ts`, but an `<img>` or media element loads its URL inside the
 * browser itself: a 401 there never reaches application code, and surfaces
 * only as a resource error event on the element — a broken thumbnail with
 * no explanation until the page is reloaded and every URL re-derived with
 * a fresh token.
 *
 * This installs one capture-phase `error` listener on the window. Resource
 * errors do not bubble, but capture sees them, so a single listener covers
 * every current and future element without each component opting in. Only
 * URLs carrying partyline's token parameter are touched — a plain asset
 * that failed for its own reasons stays failed — and each element gets
 * exactly one recovery, so a genuinely broken resource cannot loop.
 */

import { readAccessToken, refreshAccessToken } from "./http";

const TOKEN_PARAM = "token";
const RECOVERED_FLAG = "data-auth-recovered";

type MediaElement = HTMLImageElement | HTMLAudioElement | HTMLVideoElement;

function isMediaElement(node: EventTarget | null): node is MediaElement {
  return (
    node instanceof HTMLImageElement || node instanceof HTMLAudioElement || node instanceof HTMLVideoElement
  );
}

export function installResourceAuthRecovery(scope: Window = window): () => void {
  const recover = (event: Event): void => {
    void recoverSource(event);
  };
  scope.addEventListener("error", recover, true);
  return () => {
    scope.removeEventListener("error", recover, true);
  };
}

async function recoverSource(event: Event): Promise<void> {
  const target = event.target;
  if (!isMediaElement(target) || target.hasAttribute(RECOVERED_FLAG)) return;
  let url: URL;
  try {
    url = new URL(target.src, window.location.href);
  } catch {
    return;
  }
  if (!url.searchParams.has(TOKEN_PARAM)) return;
  try {
    await refreshAccessToken();
  } catch {
    return; // the refresh path already reported the expired session
  }
  const fresh = readAccessToken();
  if (!fresh) return;
  target.setAttribute(RECOVERED_FLAG, "");
  url.searchParams.set(TOKEN_PARAM, fresh);
  target.src = url.href;
}
