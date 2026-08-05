/**
 * Who this browser says it is.
 *
 * Two separate things, and conflating them breaks a real case:
 *
 *   - the **handle** is the name on your messages, and you can change it;
 *   - the **client id** is this browser, minted once and never shown. It is
 *     what lets a reload reclaim a handle whose socket the server still
 *     believes is live, while a genuinely different browser is refused.
 */

const HANDLE_KEY = "partyline_user";
const CLIENT_KEY = "partyline_client_id";

export const RESERVED_HANDLES = new Set(["all", "system"]);

export const readHandle = () => localStorage.getItem(HANDLE_KEY);

export function writeHandle(handle) {
  localStorage.setItem(HANDLE_KEY, handle);
  return handle;
}

/** Handles are one word: spaces become hyphens rather than being rejected. */
export const normalizeHandle = (raw) => raw.trim().replace(/\s+/g, "-").slice(0, 32);

export const isReserved = (handle) => RESERVED_HANDLES.has(handle.toLowerCase());

/** Mint on first use and keep it forever; `randomUUID` needs a secure context,
 *  and partyline over plain http on a LAN address is not one. */
export function readOrMintClientId() {
  const existing = localStorage.getItem(CLIENT_KEY);
  if (existing) return existing;

  const id =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : [...crypto.getRandomValues(new Uint8Array(16))]
          .map((byte) => byte.toString(16).padStart(2, "0"))
          .join("");
  localStorage.setItem(CLIENT_KEY, id);
  return id;
}
