/**
 * The REST surface, in one place.
 *
 * Every call goes through `request()`, so a failure arrives as an `ApiError`
 * carrying the server's own `detail` string rather than each call site
 * re-inventing `try { (await res.json()).detail } catch {}` — which the page
 * used to do eight times, three of them subtly differently.
 */

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * @param {string} path
 * @param {{method?: string, body?: unknown, fallback?: string}} [options]
 * @returns {Promise<any>}
 */
async function request(path, { method = "GET", body, fallback } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // A dead server is not a 500; it never answers at all.
    throw new ApiError(fallback ?? "the line is not reachable", 0);
  }

  if (!response.ok) {
    let detail = fallback ?? `request failed (${response.status})`;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      /* a non-JSON error body is still an error; keep the fallback wording */
    }
    throw new ApiError(detail, response.status);
  }

  return response.status === 204 ? null : response.json();
}

export const api = {
  version: () => request("/api/version"),
  running: () => request("/api/running"),
  shutdown: () => request("/api/shutdown", { method: "POST", body: {}, fallback: "could not stop partyline" }),

  adapters: () => request("/api/adapters"),
  importAdapters: (repository, ref) =>
    request("/api/adapters/import", { method: "POST", body: { repository, ref: ref || null }, fallback: "import failed" }),

  conversations: (archived = false) => request(`/api/conversations${archived ? "?archived=1" : ""}`),
  conversation: (id) => request(`/api/conversations/${id}`),
  createConversation: (name) => request("/api/conversations", { method: "POST", body: { name } }),
  renameConversation: (id, name, sender) =>
    request(`/api/conversations/${id}/name`, { method: "PUT", body: { name, sender }, fallback: "could not rename line" }),
  setTopic: (id, topic, sender) =>
    request(`/api/conversations/${id}/topic`, { method: "PUT", body: { topic, sender }, fallback: "could not save topic" }),
  archiveConversation: (id) =>
    request(`/api/conversations/${id}`, { method: "DELETE", fallback: "could not delete line" }),
  restoreConversation: (id) =>
    request(`/api/conversations/${id}/restore`, { method: "POST", fallback: "could not restore line" }),
  purgeConversation: (id) =>
    request(`/api/conversations/${id}/purge`, { method: "DELETE", fallback: "could not delete forever" }),

  attach: (convId, payload) =>
    request(`/api/conversations/${convId}/attachments`, { method: "POST", body: payload, fallback: "attach failed" }),
  detach: (attId) => request(`/api/attachments/${attId}`, { method: "DELETE", fallback: "could not detach" }),
  resume: (attId) => request(`/api/attachments/${attId}/resume`, { method: "POST", fallback: "resume failed" }),
  screen: (attId) => request(`/api/attachments/${attId}/screen`, { fallback: "attachment is not live" }),
  sendKey: (attId, key) =>
    request(`/api/attachments/${attId}/keys`, { method: "POST", body: { key }, fallback: "could not send key" }),

  presets: () => request("/api/presets"),
  savePreset: (preset) =>
    preset.id
      ? request(`/api/presets/${preset.id}`, { method: "PUT", body: preset, fallback: "save failed" })
      : request("/api/presets", { method: "POST", body: preset, fallback: "save failed" }),
  deletePreset: (id) => request(`/api/presets/${id}`, { method: "DELETE", fallback: "could not delete preset" }),
};
