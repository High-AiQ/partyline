/**
 * Message body rendering.
 *
 * This used to be a hand-rolled regex parser. `marked` does the parsing now and
 * DOMPurify does the sanitising, so an injected `<img onerror>` or a
 * `javascript:` href is stripped by a library that exists to strip them rather
 * than by the order two regexes happen to run in.
 *
 * The old parser's central invariant is kept: **escape first, then parse.** It
 * is not redundant with DOMPurify. Chat is prose, not a document — a message
 * saying `use <b> for bold` should show those characters, and without escaping
 * first, markup that DOMPurify happens to allow would render. That is not a
 * script hazard but it is a spoofing one: `<span class="mention">@ops</span>`
 * would draw a fake mention highlight in a room where mentions mean something.
 * Escaping settles it at the source; DOMPurify is then defence in depth.
 *
 * Two behaviours from the original are deliberate and preserved:
 *
 *   - **Block markdown is for processes only.** People get inline formatting —
 *     `code`, **bold**, links — but not headings, lists, tables or rules. A
 *     human typing "#1 issue" or "- and another thing" means it literally, and
 *     turning a chat line into a document is a worse misreading than leaving a
 *     stray asterisk visible. Processes emit real markdown, so they get it all.
 *     (`parseInline` draws exactly the line the old hand-rolled `mdInline` did.)
 *   - **@mentions are highlighted after sanitising**, by walking text nodes.
 *     Doing it on the HTML string would mean a handle could be spelled with
 *     entities to smuggle markup past the sanitiser.
 */

import { Marked } from "marked";
import DOMPurify, { type Config as DomPurifyConfig } from "dompurify";

/** Handles run to the first non-handle character; trailing `.`/`-`/`_` is sentence
 *  punctuation, not part of the name. "thanks @greg." mentions greg — and the
 *  highlight has to agree with how the server routes, or the UI is lying. */
const MENTION = /(^|\s)@([A-Za-z0-9][A-Za-z0-9_.-]*)/g;

/** Headings stay close to body size: this is a chat line, not a document, and a
 *  28px h1 in a message bubble reads as shouting. Levels past 3 flatten to 3. */
const marked = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    heading({ tokens, depth }) {
      const level = Math.min(depth, 3);
      return `<div class="md-h md-h${String(level)}">${this.parser.parseInline(tokens)}</div>`;
    },
  },
});

/**
 * Text becomes text. Runs before `marked`, so nothing in a message body can be
 * markup by the time there is a parser to be fooled.
 *
 * `>` is deliberately left alone. Only `<` can open a tag, so escaping `>` buys
 * no safety — and it costs blockquotes, because `&gt; quoted` is not something
 * a markdown parser recognises. The old hand-rolled parser escaped it and then
 * had to match `^\s*&gt;` to get them back; not escaping it is the same result
 * without the special case.
 */
const escapeHtml = (text: string): string =>
  text.replace(/[&<"]/g, (character) =>
    character === "&" ? "&amp;" : character === "<" ? "&lt;" : "&quot;",
  );

/** The only classes this renderer emits. Anything else on a node did not come
 *  from us, so it does not survive — belt and braces alongside the escaping. */
const OUR_CLASSES = new Set(["md-h", "md-h1", "md-h2", "md-h3"]);

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (!(node instanceof Element)) return;
  // Links leave the app, so they must not carry the opener with them.
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
  if (!node.hasAttribute("class")) return;
  const kept = [...node.classList].filter((name) => OUR_CLASSES.has(name));
  if (kept.length) node.setAttribute("class", kept.join(" "));
  else node.removeAttribute("class");
});

const PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    "p",
    "br",
    "hr",
    "div",
    "span",
    "b",
    "strong",
    "i",
    "em",
    "s",
    "del",
    "code",
    "pre",
    "a",
    "ul",
    "ol",
    "li",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
  ],
  ALLOWED_ATTR: ["href", "class", "target", "rel"],
  // Anything not on this list — `javascript:`, `data:`, `vbscript:` — is dropped.
  ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
  RETURN_DOM_FRAGMENT: true,
} as const satisfies DomPurifyConfig;

/**
 * Wrap every @mention in the tree in a highlight span.
 *
 * Walks text nodes rather than the HTML string, so this cannot introduce markup
 * and cannot be tricked by an entity-encoded handle. Anything already inside a
 * link or a code span is left alone: `@example` in a code sample is a literal.
 */
function highlightMentions(root: HTMLElement, doc: Document): HTMLElement {
  const walker = doc.createTreeWalker(root, 4 /* SHOW_TEXT */);
  const targets: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!(node instanceof Text)) continue;
    if (node.parentElement?.closest("a, code")) continue;
    if (MENTION.test(node.nodeValue ?? "")) targets.push(node);
    MENTION.lastIndex = 0;
  }

  for (const node of targets) {
    const fragment = doc.createDocumentFragment();
    const value = node.nodeValue ?? "";
    let cursor = 0;
    for (const match of value.matchAll(MENTION)) {
      const [whole = "", lead = "", name = ""] = match;
      const handle = name.replace(/[.\-_]+$/, "");
      fragment.append(value.slice(cursor, match.index) + lead);

      const span = doc.createElement("span");
      span.className = "mention";
      span.textContent = "@" + handle;
      fragment.append(span, name.slice(handle.length));

      cursor = match.index + whole.length;
    }
    fragment.append(value.slice(cursor));
    node.replaceWith(fragment);
  }
  return root;
}

/**
 * Render one message body to trusted HTML.
 *
 * @param {string} body  the raw message text
 * @param {boolean} rich full block markdown (processes) vs inline only (people)
 * @returns {string} HTML that is safe to assign to innerHTML
 */
export function renderMessage(body: string | undefined, rich = false): string {
  const source = escapeHtml(body ?? "");
  // `parse`/`parseInline` are typed as possibly-async for the sake of async
  // extensions; this instance has none, so both are synchronous here.
  const parsed = rich ? marked.parse(source) : marked.parseInline(source);
  if (typeof parsed !== "string") {
    throw new Error("the message renderer requires synchronous Marked extensions");
  }
  const raw = parsed;
  const doc = DOMPurify.sanitize(raw, PURIFY_CONFIG);
  const host = document.createElement("div");
  host.append(doc);
  return highlightMentions(host, document).innerHTML;
}

/** Stable per-name colour, so a handle looks the same everywhere it appears. */
export function hue(name: string): number {
  let h = 0;
  for (const character of name) h = (h * 31 + character.charCodeAt(0)) % 360;
  return h;
}

/** The colour a sender's name is drawn in. System lines are deliberately plain. */
type SenderType = "human" | "agent" | "system";

export function senderColor(sender: string, senderType: SenderType): string {
  if (senderType === "system") return "";
  const agent = senderType === "agent";
  return `hsl(${String(hue(sender.toLowerCase()))} ${agent ? "55%" : "40%"} ${agent ? "68%" : "72%"})`;
}
