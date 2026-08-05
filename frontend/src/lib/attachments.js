/**
 * Which jacks to draw, and what they can do.
 *
 * An attachment row is history: detaching and reattaching `@sol` leaves two
 * rows behind, and a resumed one leaves a third. The board shows *handles*, not
 * rows, so these functions collapse that history down to one jack per handle.
 */

const LIVE = new Set(["running", "starting"]);

/** Is this attachment one the server would currently route a mention to? */
export const isLive = (attachment) => LIVE.has(attachment?.status);

/**
 * One jack per handle: the newest attachment, except that a live one always
 * beats a dead one however old it is.
 *
 * The exception matters. Resume spawns a *new* attachment row and the old one
 * settles to `exited` moments later, out of order over the socket — without
 * "live wins" the board can end up showing the corpse and hiding the process
 * that is actually on the line.
 */
export function latestJacks(attachments) {
  const byHandle = new Map();
  for (const attachment of [...attachments].sort((a, b) => a.created_at - b.created_at)) {
    const handle = attachment.name.toLowerCase();
    const previous = byHandle.get(handle);
    if (!previous || isLive(attachment) || !isLive(previous)) byHandle.set(handle, attachment);
  }
  return [...byHandle.values()];
}

/** Does this adapter know how to reopen a previous session? */
export function canResume(adapters, adapterId) {
  const adapter = adapters.find((a) => a.id === adapterId);
  return Boolean(adapter?.capabilities?.resume);
}

/**
 * Should this jack offer a resume button?
 *
 * Both halves, in one place. Offering resume beside peek on a *running*
 * process invites someone to respawn a process that is already on the line —
 * so the liveness check is not presentation, and keeping it here means a call
 * site cannot apply half the rule.
 */
export const canResumeJack = (adapters, attachment) =>
  !isLive(attachment) && canResume(adapters, attachment.adapter);

/** The label an adapter gets in the picker. `raw` is the only one that needs a gloss. */
export const adapterLabel = (id) => (id === "raw" ? "raw — any process" : id);
