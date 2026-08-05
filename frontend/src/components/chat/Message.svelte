<script>
  /**
   * One line in the feed.
   *
   * `{@html}` is safe here and only here: `renderMessage` escapes the body,
   * parses it, and runs the result through DOMPurify. Nothing else in this app
   * should reach for `{@html}` on a message body.
   */
  import { renderMessage, senderColor } from "../../lib/markdown.js";

  let { message } = $props();

  const isSystem = $derived(message.sender_type === "system");
  const body = $derived(renderMessage(message.body, message.sender_type === "agent"));
  const when = $derived(
    new Date(message.created_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  );
</script>

<div class="msg" class:system={isSystem}>
  {#if !isSystem}
    <div class="head">
      <span class="who {message.sender_type}" style:color={senderColor(message.sender, message.sender_type)}>
        {message.sender}
      </span>
      <span class="when">{when}</span>
    </div>
  {/if}
  <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitised in renderMessage -->
  <div class="body" class:rich={message.sender_type === "agent"}>{@html body}</div>
</div>

<style>
  .msg { margin: 0 0 14px; max-width: 860px; animation: arrive 0.28s ease both; }
  .head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 2px; }
  .who { font-weight: 600; font-size: 12.5px; }
  /* A process gets a patch-cable arrow, so the eye can sort people from
     machines without reading a single name. */
  .who.agent::before { content: "▸ "; color: var(--color-copper); font-weight: 400; }
  .when { color: var(--color-cream-faint); font-size: 10px; }

  .body { white-space: pre-wrap; word-wrap: break-word; color: var(--color-cream); }
  /* Block markdown brings its own paragraphs, so pre-wrap would double every
     gap. Rich bodies wrap normally and let the block margins do the spacing. */
  .body.rich { white-space: normal; }

  .msg.system { max-width: none; text-align: center; margin: 18px 0; }
  .msg.system .body {
    display: inline-block;
    color: var(--color-cream-faint);
    font-size: 11px;
    font-style: italic;
    border-top: 1px dashed var(--color-line);
    border-bottom: 1px dashed var(--color-line);
    padding: 3px 18px;
    max-width: 100%;
    overflow-wrap: anywhere;
  }

  /* ── rendered message bodies ──
     These target markup produced by renderMessage, so they are :global — but
     scoped under .body, which only this component draws. */
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
  .body :global(pre code) { background: none; border: 0; padding: 0; }

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
  .body :global(.md-h1) { font-size: 19px; }
  .body :global(.md-h2) { font-size: 17px; }
  .body :global(.md-h3) {
    font-size: 15px;
    font-style: normal;
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--color-cream-dim);
    letter-spacing: 0.02em;
  }
  .body :global(.md-h:first-child) { margin-top: 0; }

  .body :global(p) { margin: 0 0 8px; }
  .body :global(p:last-child) { margin-bottom: 0; }
  /* Tailwind's preflight sets `list-style: none` on ul/ol, which is right for
     navigation and wrong for prose. A process writing a list means a list. */
  .body :global(ul) { list-style: disc; margin: 6px 0 6px 4px; padding-left: 18px; }
  .body :global(ol) { list-style: decimal; margin: 6px 0 6px 4px; padding-left: 18px; }
  .body :global(li) { margin: 1px 0; }
  .body :global(ul li::marker) { color: var(--color-copper); }
  .body :global(ol li::marker) { color: var(--color-copper); font-size: 11px; }
  .body :global(blockquote) {
    margin: 8px 0;
    padding: 2px 0 2px 12px;
    border-left: 2px solid var(--color-line);
    color: var(--color-cream-dim);
    font-style: italic;
  }
  .body :global(hr) { border: 0; border-top: 1px dashed var(--color-line); margin: 12px 0; }
  .body :global(a) {
    color: var(--color-copper-hot);
    text-decoration: none;
    border-bottom: 1px solid rgb(217 142 74 / 0.35);
  }
  .body :global(a:hover) { border-bottom-color: var(--color-copper-hot); }
  .body :global(table) {
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 12.5px;
    display: block;
    overflow-x: auto;
    max-width: 100%;
  }
  .body :global(th), .body :global(td) {
    border: 1px solid var(--color-line);
    padding: 4px 10px;
    text-align: left;
    vertical-align: top;
  }
  .body :global(th) { background: var(--color-ink-3); color: var(--color-cream-dim); font-weight: 600; }
  .body :global(s) { color: var(--color-cream-faint); }
</style>
