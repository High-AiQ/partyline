<script lang="ts">
  /**
   * Where you say things.
   *
   * The textarea owns the caret, so it also owns the autocomplete's keyboard:
   * while the popover is open, arrows and plain Enter belong to it and never
   * reach the send path; Shift+Enter remains the newline shortcut. That
   * precedence is the whole reason this is one component.
   */
  import MentionPopover from "./MentionPopover.svelte";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { layout } from "../../state/layout.svelte.js";
  import { insertNewline } from "../../lib/composer";
  import { applyMention, mentionCandidates, mentionToken } from "../../lib/mentions";
  import type { MentionToken } from "../../lib/mentions";
  import type { MentionCandidate } from "../../lib/mentions";

  let box = $state<HTMLTextAreaElement | null>(null);
  let token = $state<MentionToken | null>(null);
  let selected = $state(0);

  // A handle dropped in from the board should leave the caret at the end, ready
  // to keep typing, rather than wherever it happened to be.
  $effect(() => {
    void draft.externalEdits;
    if (!box) return;
    const end = draft.text.length;
    box.focus();
    box.setSelectionRange(end, end);
    resize();
  });

  const candidates = $derived<MentionCandidate[]>(
    token ? mentionCandidates(token.prefix, room.attachments, room.humans) : [],
  );
  const popoverOpen = $derived(Boolean(token) && candidates.length > 0);

  /** Grow with the text, up to a point; past that it scrolls. */
  const MAX_HEIGHT = 180;
  function resize(): void {
    if (!box) return;
    box.style.height = "auto";
    box.style.height = String(Math.min(box.scrollHeight, MAX_HEIGHT)) + "px";
  }

  function refreshToken(): void {
    token = room.conversation ? mentionToken(draft.text, box?.selectionStart ?? 0) : null;
    selected = 0;
  }

  function pick(index: number): void {
    const candidate = candidates[index];
    if (!candidate || !token) {
      closeToken();
      return;
    }
    const next = applyMention(draft.text, token, candidate.name);
    draft.text = next.value;
    closeToken();
    // Restore the caret after Svelte has written the new value back.
    requestAnimationFrame(() => {
      box?.setSelectionRange(next.caret, next.caret);
      box?.focus();
      resize();
    });
  }

  const closeToken = () => {
    token = null;
    selected = 0;
  };

  function send(): void {
    if (!room.say(draft.text)) return;
    draft.clear();
    closeToken();
    requestAnimationFrame(resize);
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === "j") {
      // Chrome and Firefox use Ctrl+J for the downloads panel; preventDefault keeps the shortcut here.
      event.preventDefault();
      const next = insertNewline(draft.text, box?.selectionStart ?? 0, box?.selectionEnd ?? 0);
      draft.text = next.value;
      closeToken();
      requestAnimationFrame(() => {
        box?.setSelectionRange(next.caret, next.caret);
        box?.focus();
        resize();
      });
      return;
    }
    if (popoverOpen) {
      const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
      if (step) {
        event.preventDefault();
        selected = (selected + step + candidates.length) % candidates.length;
        return;
      }
      if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
        event.preventDefault();
        pick(selected);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeToken();
        return;
      }
    }
    // Enter sends on a keyboard, where Shift+Enter is right there for a new
    // line. On a phone it must not: the on-screen return key is the only way
    // to break a line, and a composer that fires off a half-written message
    // every time someone reaches for a paragraph is unusable. Tap send.
    if (event.key === "Enter" && !event.shiftKey && !layout.narrow) {
      event.preventDefault();
      send();
    }
  }
</script>

<div id="composer">
  {#if popoverOpen}
    <MentionPopover {candidates} {selected} onpick={pick} />
  {/if}

  <div class="box">
    <textarea
      id="input"
      bind:this={box}
      bind:value={draft.text}
      rows="1"
      placeholder="say something… @name to ring an agent"
      aria-label="message"
      onkeydown={onKeydown}
      oninput={() => {
        resize();
        refreshToken();
      }}
      onclick={refreshToken}
      onblur={() => setTimeout(closeToken, 150)}></textarea>
    <button id="send" class="primary" type="button" onclick={send}>send</button>
  </div>
  <div class="hint">
    enter to send · shift+enter or ctrl+j for a new line · agents only wake when @mentioned · @all rings every
    running agent
  </div>
</div>

<style>
  #composer {
    padding: 14px 28px 20px;
    border-top: 1px solid var(--color-line);
    position: relative;
  }
  .box {
    display: flex;
    align-items: flex-end;
    gap: 12px;
    background: var(--color-ink-2);
    border: 1px solid var(--color-line);
    border-radius: 6px;
    padding: 10px 12px;
    transition: border-color 0.15s;
  }
  .box:focus-within {
    border-color: var(--color-copper);
  }
  #input {
    flex: 1;
    background: none;
    border: 0;
    outline: 0;
    resize: none;
    color: var(--color-cream);
    font: inherit;
    max-height: 180px;
    min-height: 22px;
  }
  .hint {
    color: var(--color-cream-faint);
    font-size: 10px;
    margin-top: 6px;
  }

  @media (max-width: 899px) {
    #composer {
      padding: 10px 12px 14px;
    }
    /* Three lines of keyboard advice, none of which applies to a touch
       keyboard, on the screen with the least room to spare. */
    .hint {
      display: none;
    }
  }
  #send {
    align-self: flex-end;
  }
</style>
