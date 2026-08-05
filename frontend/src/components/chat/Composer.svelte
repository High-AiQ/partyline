<script>
  /**
   * Where you say things.
   *
   * The textarea owns the caret, so it also owns the autocomplete's keyboard:
   * while the popover is open, arrows and Enter belong to it and never reach
   * the send path. That precedence is the whole reason this is one component.
   */
  import MentionPopover from "./MentionPopover.svelte";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { applyMention, mentionCandidates, mentionToken } from "../../lib/mentions.js";

  let box = $state(null);
  let token = $state(null);
  let selected = $state(0);

  // A handle dropped in from the board should leave the caret at the end, ready
  // to keep typing, rather than wherever it happened to be.
  $effect(() => {
    draft.externalEdits;
    if (!box) return;
    const end = draft.text.length;
    box.focus();
    box.setSelectionRange(end, end);
    resize();
  });

  const candidates = $derived(token ? mentionCandidates(token.prefix, room.attachments, room.humans) : []);
  const popoverOpen = $derived(Boolean(token) && candidates.length > 0);

  /** Grow with the text, up to a point; past that it scrolls. */
  const MAX_HEIGHT = 180;
  function resize() {
    if (!box) return;
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight, MAX_HEIGHT) + "px";
  }

  function refreshToken() {
    token = room.conversation ? mentionToken(draft.text, box?.selectionStart ?? 0) : null;
    selected = 0;
  }

  function pick(index) {
    const candidate = candidates[index];
    if (!candidate || !token) return closeToken();
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

  function send() {
    if (!room.say(draft.text)) return;
    draft.clear();
    closeToken();
    requestAnimationFrame(resize);
  }

  function onKeydown(event) {
    if (popoverOpen) {
      const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
      if (step) {
        event.preventDefault();
        selected = (selected + step + candidates.length) % candidates.length;
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
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
    if (event.key === "Enter" && !event.shiftKey) {
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
    enter to send · shift+enter for a new line · agents only wake when @mentioned · @all rings every running
    agent
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
  #send {
    align-self: flex-end;
  }
</style>
