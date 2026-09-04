/**
 * Turn what someone typed into the Start-fresh dialog into a request, or say
 * why it cannot be one. Pure, so the rules are testable without a dialog.
 */

import type { AttachmentFreshRequest } from "./attachment-contracts";

export type FreshRequestOutcome =
  { ok: true; request: AttachmentFreshRequest } | { ok: false; error: string };

const WHOLE_NUMBER = /^\d+$/;

/**
 * An empty box is "no boundary"; anything else must be a positive whole number
 * that JSON can carry exactly. Zero is refused on purpose: it would mean
 * "replay the whole line", which is the flood a fresh start exists to avoid.
 * Past the safe range the number would round or serialize as null, and the
 * server would replay from the wrong place.
 */
const parseBoundary = (typed: string): number | null | undefined => {
  const trimmed = typed.trim();
  if (!trimmed) return undefined;
  if (!WHOLE_NUMBER.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
};

const withCheckpoint = (checkpoint: string): AttachmentFreshRequest => (checkpoint ? { checkpoint } : {});

const withBoundary = (
  request: AttachmentFreshRequest,
  boundary: number | undefined,
): AttachmentFreshRequest => (boundary === undefined ? request : { ...request, after_message_id: boundary });

/**
 * A boundary without a checkpoint is refused, matching the server: replaying
 * messages "after" a point only makes sense relative to a recorded state.
 */
export function buildFreshRequest(checkpointTyped: string, boundaryTyped: string): FreshRequestOutcome {
  const checkpoint = checkpointTyped.trim();
  const boundary = parseBoundary(boundaryTyped);
  if (boundary === null) return { ok: false, error: "the message id must be a positive whole number" };
  if (boundary !== undefined && !checkpoint) {
    return { ok: false, error: "a replay boundary needs a checkpoint to replay from" };
  }
  return { ok: true, request: withBoundary(withCheckpoint(checkpoint), boundary) };
}
