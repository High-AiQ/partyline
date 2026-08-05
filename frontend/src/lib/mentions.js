/**
 * The @ autocomplete: who is on the line, and what the caret is asking for.
 *
 * Kept separate from the composer because the ranking is a real rule with real
 * consequences — mentioning a dead handle silently does nothing — and a rule
 * like that should be testable without a textarea.
 */

import { isLive, latestJacks } from "./attachments.js";

/** An @ token being typed: at the start of the line or after a space, up to the caret. */
const TOKEN = /(^|\s)@([A-Za-z0-9_.-]*)$/;

/**
 * The token under the caret, or null if the caret is not in one.
 * `start` is the index of the `@`, so a pick can splice over it.
 */
export function mentionToken(value, caret) {
  const upto = value.slice(0, caret);
  const match = TOKEN.exec(upto);
  if (!match) return null;
  return { prefix: match[2], start: upto.length - match[2].length - 1 };
}

/** Live handles first, then dead processes, then humans; alphabetical within each. */
const rank = (candidate) => (isLive(candidate) ? 0 : candidate.status ? 1 : 2);

/**
 * Everyone the prefix could mean.
 *
 * @param prefix    what has been typed after the `@`
 * @param attachments the conversation's attachment rows
 * @param humans    handles seen speaking on this line
 */
export function mentionCandidates(prefix, attachments, humans) {
  const agents = latestJacks(attachments).map((a) => ({ name: a.name, kind: a.adapter, status: a.status }));
  const people = [...humans].map((name) => ({ name, kind: "human", status: null }));
  const needle = prefix.toLowerCase();

  // One entry per handle, the process winning over the person. A handle is
  // released when its process dies, so a human may legitimately be using a name
  // a dead jack still carries — and offering it twice is both a redundant
  // choice and, since the list is keyed by name, a duplicate-key crash.
  const byHandle = new Map();
  for (const candidate of [...agents, ...people]) {
    const handle = candidate.name.toLowerCase();
    if (!handle.startsWith(needle) || byHandle.has(handle)) continue;
    byHandle.set(handle, candidate);
  }

  const candidates = [...byHandle.values()].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  // The megaphone is deliberately last, and only offered when it would do
  // something: @all rings every running process at once.
  if ("all".startsWith(needle) && agents.some(isLive)) {
    candidates.push({ name: "all", kind: "rings every agent", status: null, all: true });
  }
  return candidates;
}

/**
 * Splice a chosen handle over the token being typed.
 * Returns the new value and where the caret should land after it.
 */
export function applyMention(value, token, name) {
  const tail = value.slice(token.start + token.prefix.length + 1);
  return {
    value: value.slice(0, token.start) + "@" + name + " " + tail,
    caret: token.start + name.length + 2,
  };
}
