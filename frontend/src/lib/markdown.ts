/**
 * Message body rendering: escape first, then `marked`, then DOMPurify, then
 * mention highlighting on text nodes. Block markdown and math/code markers are
 * for process messages only; humans keep inline-only formatting.
 */

import { Marked, type Token, type RendererThis } from "marked";
import DOMPurify, { type Config as DomPurifyConfig } from "dompurify";
import type { SenderType } from "./contracts";
import {
  byteLength,
  CODE_BLOCK_MAX_BYTES,
  CODE_LANGUAGE_ALIASES,
  MATH_DELIMITER_CONTRACT,
  MATH_MAX_EXPRESSION_BYTES,
  MATH_MAX_EXPRESSIONS_PER_MESSAGE,
  normalizeCodeLanguage,
  SUPPORTED_CODE_LANGUAGES,
} from "./markdown-contract";
import { createRichMarked } from "./markdown-math";

export {
  CODE_BLOCK_MAX_BYTES,
  CODE_LANGUAGE_ALIASES,
  MATH_DELIMITER_CONTRACT,
  MATH_MAX_EXPRESSION_BYTES,
  MATH_MAX_EXPRESSIONS_PER_MESSAGE,
  normalizeCodeLanguage,
  SUPPORTED_CODE_LANGUAGES,
};

/** Handles run to the first non-handle character; trailing `.`/`-`/`_` is sentence
 *  punctuation, not part of the name. "thanks @greg." mentions greg — and the
 *  highlight has to agree with how the server routes, or the UI is lying. */
const MENTION = /(^|\s)@([A-Za-z0-9][A-Za-z0-9_.-]*)/g;

const escapeHtml = (text: string): string =>
  text.replace(/[&<"]/g, (character) =>
    character === "&" ? "&amp;" : character === "<" ? "&lt;" : "&quot;",
  );

const OUR_CLASSES = new Set(["md-h", "md-h1", "md-h2", "md-h3"]);

const headingRenderer = {
  heading(this: RendererThis, { tokens, depth }: { tokens: Token[]; depth: number }) {
    const level = Math.min(depth, 3);
    return `<div class="md-h md-h${String(level)}">${this.parser.parseInline(tokens)}</div>`;
  },
};

function renderCodeBlock(text: string, lang: string | undefined): string {
  const normalized = lang ? normalizeCodeLanguage(lang.split(/\s+/)[0] ?? "") : null;
  const marker =
    normalized && byteLength(text) <= CODE_BLOCK_MAX_BYTES ? ` data-code-language="${normalized}"` : "";
  return `<pre><code${marker}>${text}</code></pre>`;
}

const inlineMarked = new Marked({
  gfm: true,
  breaks: false,
  renderer: headingRenderer,
});

const richMarkedForMessage = (): Marked =>
  createRichMarked({
    ...headingRenderer,
    code({ text, lang }: { text: string; lang?: string }) {
      return renderCodeBlock(text, lang);
    },
  });

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (!(node instanceof Element)) return;
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
  for (const attribute of [...node.attributes]) {
    if (
      attribute.name.startsWith("data-") &&
      attribute.name !== "data-code-language" &&
      attribute.name !== "data-math"
    ) {
      node.removeAttribute(attribute.name);
    }
  }
  const lang = node.getAttribute("data-code-language");
  if (lang && !SUPPORTED_CODE_LANGUAGES.has(lang)) node.removeAttribute("data-code-language");
  const math = node.getAttribute("data-math");
  if (math && math !== "inline" && math !== "display") node.removeAttribute("data-math");
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
  ALLOWED_ATTR: ["href", "class", "target", "rel", "data-code-language", "data-math"],
  ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
  RETURN_DOM_FRAGMENT: true,
} as const satisfies DomPurifyConfig;

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

export function renderMessage(body: string | undefined, rich = false): string {
  const source = escapeHtml(body ?? "");
  const parser = rich ? richMarkedForMessage() : inlineMarked;
  const parsed = rich ? parser.parse(source) : parser.parseInline(source);
  if (typeof parsed !== "string") {
    throw new Error("the message renderer requires synchronous Marked extensions");
  }
  const doc = DOMPurify.sanitize(parsed, PURIFY_CONFIG);
  const host = document.createElement("div");
  host.append(doc);
  return highlightMentions(host, document).innerHTML;
}

export function hue(name: string): number {
  let h = 0;
  for (const character of name) h = (h * 31 + character.charCodeAt(0)) % 360;
  return h;
}

export function senderColor(sender: string, senderType: SenderType): string {
  if (senderType === "system") return "";
  const agent = senderType === "agent";
  return `hsl(${String(hue(sender.toLowerCase()))} ${agent ? "55%" : "40%"} ${agent ? "68%" : "72%"})`;
}
