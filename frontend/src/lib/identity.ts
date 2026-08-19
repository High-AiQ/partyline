/**
 * The browser's stable client id. Human identity comes from the authenticated
 * user; this id only distinguishes browser connections belonging to that user.
 */

const CLIENT_KEY = "partyline_client_id";

/** Mint once per tab and retain it across reloads. `sessionStorage` is
 *  intentionally tab-scoped: two tabs belonging to one authenticated account
 *  may hold sockets concurrently, while a reload can still supersede its own
 *  half-open connection. */
export function readOrMintClientId(): string {
  let existing: string | null = null;
  try {
    existing = sessionStorage.getItem(CLIENT_KEY);
  } catch {
    // A storage policy may prevent reconnect takeover, but must not crash chat.
  }
  if (existing) return existing;

  const id =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : [...crypto.getRandomValues(new Uint8Array(16))]
          .map((byte) => byte.toString(16).padStart(2, "0"))
          .join("");
  try {
    sessionStorage.setItem(CLIENT_KEY, id);
  } catch {
    // This tab can still use its in-memory id for the current document.
  }
  return id;
}
