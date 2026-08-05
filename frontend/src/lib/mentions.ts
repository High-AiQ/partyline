/** The @ autocomplete: who is on the line, and what the caret is asking for. */

import { isLive, latestJacks } from "./attachments";

const TOKEN = /(^|\s)@([A-Za-z0-9_.-]*)$/;

export interface MentionToken {
  prefix: string;
  start: number;
}

export interface MentionCandidate {
  name: string;
  kind: string;
  status: string | null;
  all?: true;
}

export interface MentionResult {
  value: string;
  caret: number;
}

interface MentionAttachment {
  name: string;
  adapter: string;
  status: string;
  created_at: number;
}

/** The token under the caret, or null if the caret is not in one. */
export function mentionToken(value: string, caret: number): MentionToken | null {
  const upto = value.slice(0, caret);
  const match = TOKEN.exec(upto);
  if (!match) return null;
  return { prefix: match[2] ?? "", start: upto.length - (match[2]?.length ?? 0) - 1 };
}

/** Live handles first, then dead processes, then humans; alphabetical within each. */
const rank = (candidate: MentionCandidate): number => (isLive(candidate) ? 0 : candidate.status ? 1 : 2);

/** Everyone the prefix could mean. */
export function mentionCandidates(
  prefix: string,
  attachments: readonly MentionAttachment[],
  humans: Iterable<string>,
): MentionCandidate[] {
  const agents: MentionCandidate[] = latestJacks(attachments).map((attachment) => ({
    name: attachment.name,
    kind: attachment.adapter,
    status: attachment.status,
  }));
  const people: MentionCandidate[] = [...humans].map((name) => ({ name, kind: "human", status: null }));
  const needle = prefix.toLowerCase();
  const byHandle = new Map<string, MentionCandidate>();
  for (const candidate of [...agents, ...people]) {
    const handle = candidate.name.toLowerCase();
    if (!handle.startsWith(needle) || byHandle.has(handle)) continue;
    byHandle.set(handle, candidate);
  }

  const candidates = [...byHandle.values()].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  if ("all".startsWith(needle) && agents.some(isLive)) {
    candidates.push({ name: "all", kind: "rings every agent", status: null, all: true });
  }
  return candidates;
}

/** Splice a chosen handle over the token being typed. */
export function applyMention(value: string, token: MentionToken, name: string): MentionResult {
  const tail = value.slice(token.start + token.prefix.length + 1);
  return {
    value: value.slice(0, token.start) + "@" + name + " " + tail,
    caret: token.start + name.length + 2,
  };
}
