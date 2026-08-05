/**
 * Deep links to a line: `#/c/<conversation id>`.
 *
 * A hash route rather than a path, because the server serves one page and
 * should not have to learn about client routes to keep a refresh working.
 */

const ROUTE = /^#\/c\/([^/]+)$/;

export const conversationRoute = (id) => "#/c/" + encodeURIComponent(id);

/** The conversation id in the current URL, or null. A malformed escape is not a route. */
export function routedConversationId(hash = location.hash) {
  const match = hash.match(ROUTE);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

/**
 * Point the URL at a line.
 *
 * `replace` is for arriving *from* the URL — pushing there would put the state
 * we just restored onto the history stack a second time, so Back would appear
 * to do nothing.
 */
export function setConversationRoute(id, { replace = false } = {}) {
  const hash = conversationRoute(id);
  if (location.hash === hash) return;
  history[replace ? "replaceState" : "pushState"]({}, "", location.pathname + location.search + hash);
}

export function clearConversationRoute() {
  history.replaceState({}, "", location.pathname + location.search);
}
