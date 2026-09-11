/**
 * What is currently typed into the composer — one draft per line.
 *
 * It lives outside the composer because the board writes to it: clicking a
 * jack's name drops that handle into the message you are composing. Passing a
 * callback up to `App` and back down to `Board` would thread two components
 * through a relationship neither of them has.
 *
 * Drafts are keyed by conversation id, so text never travels between lines:
 * half a message aimed at line A must not sit in the composer when you switch
 * to line B, where an `@name` typed for A's participants can ring a same-named
 * process that lives on B. `room.open()`/`leave()` drive
 * `openLine()`/`leaveLine()`.
 */

import { SvelteMap } from "svelte/reactivity";

export const DRAFT_STORAGE_KEY = "partyline.composer-draft";

export interface DraftStorage {
  getItem?(key: string): string | null;
  setItem?(key: string, value: string): void;
  removeItem?(key: string): void;
}

export function draftStorageKey(conversationId: string): string {
  return `${DRAFT_STORAGE_KEY}:${conversationId}`;
}

function browserStorage(): Storage | null {
  try {
    return globalThis.sessionStorage;
  } catch {
    return null;
  }
}

export function restoreDraft(
  conversationId: string,
  storage: DraftStorage | null = browserStorage(),
): string {
  try {
    return storage?.getItem?.(draftStorageKey(conversationId)) ?? "";
  } catch {
    return "";
  }
}

export function persistDraft(
  conversationId: string,
  text: string,
  storage: DraftStorage | null = browserStorage(),
): void {
  try {
    if (text) storage?.setItem?.(draftStorageKey(conversationId), text);
    else storage?.removeItem?.(draftStorageKey(conversationId));
  } catch {
    // Storage can be disabled without making the composer unusable.
  }
}

export class Draft {
  /** The line whose draft the composer is showing; `null` between lines. */
  #activeId: string | null = $state(null);
  /** Every line visited this session keeps its unsent text here. */
  #texts = new SvelteMap<string, string>();
  #storage: DraftStorage | null;

  constructor(storage: DraftStorage | null = browserStorage()) {
    this.#storage = storage;
  }

  /** Bumped whenever something outside the composer edits the text or swaps
   *  the active line, so the composer knows to move the caret and resize
   *  rather than leaving both wherever the user last put them. */
  externalEdits = $state(0);

  get text(): string {
    return this.#activeId === null ? "" : (this.#texts.get(this.#activeId) ?? "");
  }

  set text(value: string) {
    if (this.#activeId === null) return; // no line open — nowhere for text to belong
    if (this.#texts.get(this.#activeId) === value) return;
    this.#texts.set(this.#activeId, value);
    persistDraft(this.#activeId, value, this.#storage);
  }

  /** Swap to a line's draft, restoring whatever was saved for it. The draft
   *  already held in memory wins over storage, which only has what the last
   *  write left behind. */
  openLine(conversationId: string): void {
    if (this.#activeId === conversationId) return;
    if (!this.#texts.has(conversationId)) {
      this.#texts.set(conversationId, restoreDraft(conversationId, this.#storage));
    }
    this.#activeId = conversationId;
    this.externalEdits++;
  }

  /** Step off the current line; every draft is kept for when its line reopens. */
  leaveLine(): void {
    this.#activeId = null;
  }

  clear(): void {
    this.text = "";
  }

  /** Append a handle, keeping exactly one space between it and what came before. */
  mention(name: string): void {
    const current = this.text;
    const lead = current && !current.endsWith(" ") ? " " : "";
    this.text = current + lead + "@" + name + " ";
    this.externalEdits++;
  }
}

export const draft = new Draft();
