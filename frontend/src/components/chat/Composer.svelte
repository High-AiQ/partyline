<script lang="ts">
  /**
   * Where you say things.
   *
   * The textarea owns the caret, so it also owns the autocomplete's keyboard:
   * while the popover is open, arrows and plain Enter belong to it and never
   * reach the send path; Shift+Enter remains the newline shortcut. That
   * precedence is the whole reason this is one component.
   */
  import { untrack } from "svelte";
  import MentionPopover from "./MentionPopover.svelte";
  import FileAttachmentPicker from "./FileAttachmentPicker.svelte";
  import ComposerDropZone from "./ComposerDropZone.svelte";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { layout } from "../../state/layout.svelte.js";
  import { insertNewline } from "../../lib/composer";
  import { api } from "../../lib/api";
  import type { FileIntake, PendingFiles } from "../../lib/files";
  import { applyMention, mentionCandidates, mentionToken } from "../../lib/mentions";
  import type { MentionToken, MentionCandidate } from "../../lib/mentions";

  let box = $state<HTMLTextAreaElement | null>(null);
  let token = $state<MentionToken | null>(null);
  let selected = $state(0);
  let pendingFiles = $state<PendingFiles>({ files: [], title: "", description: "" });
  let pickerGeneration = $state(0);
  let openPicker = $state(0);
  let fileIntake = $state<FileIntake>({ generation: 0, files: [] });
  let uploading = $state(false);
  function queueFiles(files: File[]): void {
    fileIntake = { generation: fileIntake.generation + 1, files };
  }

  // A handle dropped in from the board should leave the caret at the end. The
  // trigger is externalEdits alone — draft.text is untracked so typing can't move it.
  $effect(() => {
    void draft.externalEdits;
    if (!box) return;
    const end = untrack(() => draft.text.length);
    box.focus();
    box.setSelectionRange(end, end);
    resize();
  });

  const candidates = $derived<MentionCandidate[]>(
    token ? mentionCandidates(token.prefix, room.attachments, room.history.humans) : [],
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

  async function send(): Promise<void> {
    if (uploading) return;
    if (!pendingFiles.files.length) {
      if (!room.say(draft.text)) return;
      draft.clear();
      closeToken();
      requestAnimationFrame(resize);
      return;
    }
    const conversation = room.conversation;
    if (!conversation) return;
    uploading = true;
    try {
      await api.uploadFiles(conversation.id, {
        files: pendingFiles.files,
        body: draft.text.trim(),
        title: pendingFiles.title.trim() || null,
        description: pendingFiles.description.trim() || null,
      });
      pendingFiles = { files: [], title: "", description: "" };
      fileIntake = { generation: 0, files: [] };
      openPicker = 0;
      pickerGeneration++;
      draft.clear();
      closeToken();
      await room.resync();
      requestAnimationFrame(resize);
    } catch (error) {
      room.showNotice(error instanceof Error ? error.message : "file upload failed", "error");
    } finally {
      uploading = false;
    }
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
      void send();
    }
  }
</script>

<ComposerDropZone disabled={!room.conversation || uploading} onfiles={queueFiles}>
  {#if popoverOpen}
    <MentionPopover {candidates} {selected} onpick={pick} />
  {/if}

  {#key pickerGeneration}
    <FileAttachmentPicker
      {openPicker}
      intake={fileIntake}
      onselection={(selection: PendingFiles) => {
        pendingFiles = selection;
      }}
      onlimit={() => {
        room.showNotice("attach at most 6 files at once", "error");
      }}
    />
  {/key}

  <div
    class="box flex items-end gap-3 rounded-md border border-line bg-ink-2 px-3 py-2.5 transition-colors focus-within:border-copper"
    aria-busy={uploading}
  >
    <button
      class="attach grid size-11 flex-none place-items-center p-0 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
      type="button"
      aria-label="attach files"
      title="attach up to 6 files"
      disabled={!room.conversation || uploading}
      onclick={() => {
        openPicker++;
      }}
    >
      <svg
        class="size-[18px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l10-10a4 4 0 1 1 5.7 5.7l-10 10a2 2 0 0 1-2.9-2.8l9.3-9.3"
        />
      </svg>
    </button>
    <textarea
      id="input"
      class="max-h-[180px] min-h-[22px] flex-1 resize-none border-0 bg-transparent text-cream outline-0 [font-family:inherit]"
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
    <button
      id="send"
      class="primary min-h-11 self-end disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
      type="button"
      disabled={uploading || (!draft.text.trim() && !pendingFiles.files.length)}
      onclick={() => void send()}>{uploading ? "uploading…" : "send"}</button
    >
  </div>
  <div class="hint mt-1.5 text-[10px] text-cream-faint">
    enter to send · shift+enter or ctrl+j for a new line · agents only wake when @mentioned · @all rings every
    running agent
  </div>
</ComposerDropZone>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written. */
  @media (max-width: 899px) {
    /* Three lines of keyboard advice, none of which applies to a touch
       keyboard, on the screen with the least room to spare. */
    .hint {
      display: none;
    }
  }
</style>
