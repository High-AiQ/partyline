/** The @ autocomplete: who is on the line, and what the caret is asking for. */

import { isLive, latestJacks } from "./attachments";
import type { TextEdit } from "./composer";

/** `@name`, and `@!name` — the same mention carrying a request to interrupt first. */
const TOKEN = /(^|\s)@(!?)([A-Za-z0-9_.-]*)$/;

export interface MentionToken {
  prefix: string;
  start: number;
  /** The caret is in a `@!` token: an explicit interrupt-and-send. */
  bang: boolean;
}

export interface MentionCandidate {
  name: string;
  kind: string;
  status: string | null;
  all?: true;
  /** Only meaningful while a bang is being typed: would the server stop this
   *  process, or deliver the message as an ordinary mention? */
  interruptible?: boolean;
}

interface MentionAttachment {
  name: string;
  adapter: string;
  status: string;
  created_at: number;
}

interface InterruptCapableAdapter {
  id: string;
  capabilities?: { interrupt?: boolean | undefined };
}

/** The token under the caret, or null if the caret is not in one. */
export function mentionToken(value: string, caret: number): MentionToken | null {
  const upto = value.slice(0, caret);
  const match = TOKEN.exec(upto);
  if (!match) return null;
  const bang = match[2] === "!";
  const prefix = match[3] ?? "";
  // `start` is the index of the `@`, so the sigil's own length varies.
  return { prefix, start: upto.length - prefix.length - (bang ? 2 : 1), bang };
}

/** Live handles first, then dead processes, then humans; alphabetical within each. */
const rank = (candidate: MentionCandidate): number => (isLive(candidate) ? 0 : candidate.status ? 1 : 2);

/** Everyone the prefix could mean. */
export function mentionCandidates(
  prefix: string,
  attachments: readonly MentionAttachment[],
  humans: Iterable<string>,
  adapters: readonly InterruptCapableAdapter[] = [],
): MentionCandidate[] {
  const interrupts = new Set(
    adapters.filter((adapter) => adapter.capabilities?.interrupt === true).map((adapter) => adapter.id),
  );
  const agents: MentionCandidate[] = latestJacks(attachments).map((attachment) => ({
    name: attachment.name,
    kind: attachment.adapter,
    status: attachment.status,
    // A dead process has nothing to stop, so support alone is not enough.
    interruptible: interrupts.has(attachment.adapter) && isLive(attachment),
  }));
  const people: MentionCandidate[] = [...humans].map((name) => ({
    name,
    kind: "human",
    status: null,
    interruptible: false,
  }));
  const needle = prefix.toLowerCase();
  const byHandle = new Map<string, MentionCandidate>();
  for (const candidate of [...agents, ...people]) {
    const handle = candidate.name.toLowerCase();
    if (!handle.startsWith(needle) || byHandle.has(handle)) continue;
    byHandle.set(handle, candidate);
  }

  const candidates = [...byHandle.values()].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  if ("all".startsWith(needle) && agents.some(isLive)) {
    // `@!all` rings the room like `@all`; the server drops the bang rather
    // than stopping every process at once.
    candidates.push({
      name: "all",
      kind: "rings every agent",
      status: null,
      all: true,
      interruptible: false,
    });
  }
  return candidates;
}

/** Splice a chosen handle over the token being typed. */
export function applyMention(value: string, token: MentionToken, name: string): TextEdit {
  // Picking a name must never quietly drop the bang: the sigil the operator
  // typed is the difference between a mention and an interruption.
  const sigil = token.bang ? "@!" : "@";
  const tail = value.slice(token.start + token.prefix.length + sigil.length);
  return {
    value: value.slice(0, token.start) + sigil + name + " " + tail,
    caret: token.start + sigil.length + name.length + 1,
  };
}
