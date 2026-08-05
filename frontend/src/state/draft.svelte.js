/**
 * What is currently typed into the composer.
 *
 * It lives outside the composer because the board writes to it: clicking a
 * jack's name drops that handle into the message you are composing. Passing a
 * callback up to `App` and back down to `Board` would thread two components
 * through a relationship neither of them has.
 */

export const DRAFT_STORAGE_KEY = "partyline.composer-draft";

function browserStorage() {
  try {
    return globalThis.sessionStorage;
  } catch {
    return null;
  }
}

export function restoreDraft(storage = browserStorage()) {
  try {
    return storage?.getItem(DRAFT_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function persistDraft(text, storage = browserStorage()) {
  try {
    if (text) storage?.setItem(DRAFT_STORAGE_KEY, text);
    else storage?.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    // Storage can be disabled without making the composer unusable.
  }
}

class Draft {
  #text = $state(restoreDraft());

  get text() {
    return this.#text;
  }

  set text(value) {
    this.#text = value;
    persistDraft(value);
  }

  /** Bumped whenever something outside the composer edits the text, so the
   *  composer knows to move the caret and resize rather than leaving both
   *  wherever the user last put them. */
  externalEdits = $state(0);

  clear() {
    this.text = "";
  }

  /** Append a handle, keeping exactly one space between it and what came before. */
  mention(name) {
    const lead = this.text && !this.text.endsWith(" ") ? " " : "";
    this.text = this.text + lead + "@" + name + " ";
    this.externalEdits++;
  }
}

export const draft = new Draft();
