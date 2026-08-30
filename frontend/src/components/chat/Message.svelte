<script lang="ts">
  /**
   * One line in the feed.
   *
   * `{@html}` is safe here and only here: `renderMessage` escapes the body,
   * parses it, and runs the result through DOMPurify. Nothing else in this app
   * should reach for `{@html}` on a message body.
   */
  import { renderMessage, senderColor } from "../../lib/markdown";
  import { visibleMessageBody } from "../../lib/files";
  import ImageGrid from "./ImageGrid.svelte";
  import FileAttachments from "./FileAttachments.svelte";
  import type { ChatMessage } from "../../lib/contracts";

  interface Props {
    message: ChatMessage;
  }

  let { message }: Props = $props();

  const isSystem = $derived(message.sender_type === "system");
  const body = $derived(renderMessage(visibleMessageBody(message), message.sender_type === "agent"));
  const images = $derived(message.files.filter((file) => file.kind === "image"));
  const otherFiles = $derived(message.files.filter((file) => file.kind !== "image"));
  const when = $derived(
    new Date(message.created_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  );
  // Operational notices include multiline update and reattachment reports.
  // Their whitespace contract is the same as human-authored bodies.
  const bodyClass = $derived(
    isSystem
      ? "inline-block max-w-full whitespace-pre-wrap border-y border-dashed border-line px-[18px] py-[3px] text-[11px] text-cream-faint italic [overflow-wrap:anywhere]"
      : message.sender_type === "agent"
        ? "whitespace-normal break-words text-cream"
        : "whitespace-pre-wrap break-words text-cream",
  );
  const rootClass = $derived(isSystem ? "max-w-none text-center my-[18px]" : "max-w-[860px] mb-[14px]");
</script>

<div class="msg animate-[arrive_0.28s_ease_both] {rootClass}">
  {#if !isSystem}
    <div class="head mb-0.5 flex items-baseline gap-2.5">
      <span
        class="who font-semibold text-[12.5px] {message.sender_type}"
        style:color={senderColor(message.sender, message.sender_type)}
      >
        {message.sender}
      </span>
      <span class="when text-[10px] text-cream-faint">{when}</span>
    </div>
  {/if}
  <div class="body {bodyClass}">
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitised in renderMessage -->
    {@html body}
  </div>
  {#if images.length}
    <ImageGrid {images} />
  {/if}
  {#if otherFiles.length}
    <FileAttachments files={otherFiles} />
  {/if}
</div>

<style>
  /* A process gets a patch-cable arrow, so the eye can sort people from
       machines without reading a single name. */
  .who.agent::before {
    content: "▸ ";
    color: var(--color-copper);
    font-weight: 400;
  }

  /* ── rendered message bodies ──
       These target markup produced by renderMessage, so they are :global — but
       scoped under .body, which only this component draws. The classes come
       from the markdown renderer, not from markup we can put utilities on, so
       they stay hand-written like the shared vocabulary in app.css. */
  .body :global(.mention) {
    color: var(--color-copper-hot);
    background: rgb(217 142 74 / 0.09);
    border-radius: 3px;
    padding: 0 3px;
  }
  .body :global(code) {
    background: var(--color-ink-3);
    border: 1px solid var(--color-line);
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 12.5px;
  }
  .body :global(pre) {
    background: var(--color-ink-2);
    border: 1px solid var(--color-line);
    border-left: 2px solid var(--color-copper);
    border-radius: 4px;
    padding: 10px 14px;
    margin: 8px 0;
    overflow-x: auto;
    font-size: 12.5px;
    white-space: pre;
  }
  .body :global(pre code) {
    background: none;
    border: 0;
    padding: 0;
  }

  /* Headings stay close to body size: this is a chat line, not a document, and
       a 28px h1 in a message bubble reads as shouting. */
  .body :global(.md-h) {
    font-family: var(--font-serif);
    font-style: italic;
    font-weight: 400;
    color: var(--color-cream);
    margin: 10px 0 2px;
    line-height: 1.3;
  }
  .body :global(.md-h1) {
    font-size: 19px;
  }
  .body :global(.md-h2) {
    font-size: 17px;
  }
  .body :global(.md-h3) {
    font-size: 15px;
    font-style: normal;
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--color-cream-dim);
    letter-spacing: 0.02em;
  }
  .body :global(.md-h:first-child) {
    margin-top: 0;
  }

  .body :global(p) {
    margin: 0 0 8px;
  }
  .body :global(p:last-child) {
    margin-bottom: 0;
  }
  /* Tailwind's preflight sets `list-style: none` on ul/ol, which is right for
       navigation and wrong for prose. A process writing a list means a list. */
  .body :global(ul) {
    list-style: disc;
    margin: 6px 0 6px 4px;
    padding-left: 18px;
  }
  .body :global(ol) {
    list-style: decimal;
    margin: 6px 0 6px 4px;
    padding-left: 18px;
  }
  .body :global(li) {
    margin: 1px 0;
  }
  .body :global(ul li::marker) {
    color: var(--color-copper);
  }
  .body :global(ol li::marker) {
    color: var(--color-copper);
    font-size: 11px;
  }
  .body :global(blockquote) {
    margin: 8px 0;
    padding: 2px 0 2px 12px;
    border-left: 2px solid var(--color-line);
    color: var(--color-cream-dim);
    font-style: italic;
  }
  .body :global(hr) {
    border: 0;
    border-top: 1px dashed var(--color-line);
    margin: 12px 0;
  }
  .body :global(a) {
    color: var(--color-copper-hot);
    text-decoration: none;
    border-bottom: 1px solid rgb(217 142 74 / 0.35);
  }
  .body :global(a:hover) {
    border-bottom-color: var(--color-copper-hot);
  }
  .body :global(table) {
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 12.5px;
    display: block;
    overflow-x: auto;
    max-width: 100%;
  }
  .body :global(th),
  .body :global(td) {
    border: 1px solid var(--color-line);
    padding: 4px 10px;
    text-align: left;
    vertical-align: top;
  }
  .body :global(th) {
    background: var(--color-ink-3);
    color: var(--color-cream-dim);
    font-weight: 600;
  }
  .body :global(s) {
    color: var(--color-cream-faint);
  }
</style>
