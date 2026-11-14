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
  import VoiceInput from "./VoiceInput.svelte";
  import HandsFreeInput from "./HandsFreeInput.svelte";
  import ComposerMoreMenu from "./ComposerMoreMenu.svelte";
  import AttachButton from "./AttachButton.svelte";
  import ComposerHint from "./ComposerHint.svelte";
  import type { VoiceStatus } from "../../lib/voice";
  import { handsFree } from "../../state/hands-free.svelte.js";
  import ScreenFramesToggle from "./ScreenFramesToggle.svelte";
  import WalkthroughControl from "./WalkthroughControl.svelte";
  import { walkthrough } from "../../state/walkthrough.svelte.js";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { layout } from "../../state/layout.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import { sendFailures } from "../../state/send-failures.svelte.js";
  import { composerPlaceholder, insertNewline, MAX_MESSAGE_BODY } from "../../lib/composer";
  import { api } from "../../lib/api";
  import type { FileIntake, PendingFiles } from "../../lib/files";
  import { applyMention, mentionCandidates, mentionToken } from "../../lib/mentions";
  import type { MentionToken, MentionCandidate } from "../../lib/mentions";
  import { isLive } from "../../lib/attachments";
  import { settleFocus } from "../../lib/phone-focus";

  let box = $state<HTMLTextAreaElement | null>(null);
  let token = $state<MentionToken | null>(null);
  let selected = $state(0);
  let pendingFiles = $state<PendingFiles>({ files: [], title: "", description: "" });
  let pickerGeneration = $state(0);
  let openPicker = $state(0);
  let fileIntake = $state<FileIntake>({ generation: 0, files: [] });
  let uploading = $state(false);
  /** The mic's state for the phone menu, and the handle its Dictate item calls. */
  let voice = $state<VoiceStatus>({ busy: false, blocked: true, label: "" });
  let voiceControl = $state<{ dictate: () => void }>();
  let row = $state<HTMLDivElement | null>(null);
  let wasLive = false;
  $effect(() => {
    const live = layout.narrow && (voice.busy || handsFree.value.enabled);
    if (live === wasLive) return;
    wasLive = live;
    settleFocus(row, live, handsFree.value.enabled);
  });
  let includeScreen = $state(true);
  $effect(() => {
    if (room.screenShare?.share_id) includeScreen = true;
  });
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
    token ? mentionCandidates(token.prefix, room.attachments, room.history.humans, session.adapters) : [],
  );
  const popoverOpen = $derived(Boolean(token) && candidates.length > 0);
  const hasLiveProcess = $derived(room.attachments.some(isLive));
  const placeholder = $derived(composerPlaceholder(layout.narrow));

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
    if (!hasLiveProcess && draft.text.trim()) return;
    const attachScreen =
      includeScreen && room.screenShare?.status === "active" && !room.screenShare.walkthrough;
    if (!pendingFiles.files.length && !attachScreen) {
      if (!hasLiveProcess) return;
      const conversation = room.conversation;
      const text = draft.text;
      if (!conversation || !text.trim()) return;
      draft.clear();
      closeToken();
      requestAnimationFrame(resize);
      if (!(await room.say(text))) draft.restoreFailed(conversation.id, text);
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
        includeScreen: attachScreen,
      });
      pendingFiles = { files: [], title: "", description: "" };
      fileIntake = { generation: 0, files: [] };
      openPicker = 0;
      pickerGeneration++;
      draft.clear();
      closeToken();
      sendFailures.sent(conversation.id);
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
    if (event.key === "Enter" && !event.shiftKey && !layout.narrow && !walkthrough.active) {
      event.preventDefault();
      void send();
    }
  }
</script>

<ComposerDropZone disabled={!room.conversation || uploading} onfiles={queueFiles}>
  {#if popoverOpen}
    <MentionPopover {candidates} {selected} onpick={pick} bang={token?.bang ?? false} />
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
    bind:this={row}
    class="box flex flex-wrap items-end gap-x-2 gap-y-2 rounded-md border border-line bg-ink-2 px-3 py-2.5 transition-colors focus-within:border-copper min-[900px]:gap-x-3"
    aria-busy={uploading}
  >
    {#if !layout.narrow}<AttachButton
        disabled={!room.conversation || uploading}
        onclick={() => openPicker++}
      />{/if}
    {#if !walkthrough.active && !handsFree.value.enabled}<VoiceInput
        bind:this={voiceControl}
        {box}
        collapsed={layout.narrow}
        onstatus={(status: VoiceStatus) => (voice = status)}
        oninserted={resize}
      />{/if}
    {#if !walkthrough.active && (!layout.narrow || handsFree.value.enabled)}<HandsFreeInput />{/if}
    {#if layout.narrow && !voice.busy && !handsFree.value.enabled}
      <ComposerMoreMenu
        attachDisabled={!room.conversation || uploading}
        dictateBlocked={voice.blocked}
        dictateLabel={voice.label}
        onattach={() => openPicker++}
        ondictate={() => voiceControl?.dictate()}
      />
    {/if}
    <WalkthroughControl />
    {#if room.screenShare?.status === "active" && !room.screenShare.walkthrough}
      <ScreenFramesToggle bind:pressed={includeScreen} />
    {/if}
    <div class="flex min-w-[10rem] flex-1 items-end gap-2 min-[900px]:gap-3">
      <textarea
        id="input"
        class="max-h-[180px] min-h-7 min-w-20 flex-1 resize-none border-0 bg-transparent text-cream outline-0 [font-family:inherit]"
        bind:this={box}
        bind:value={draft.text}
        rows="1"
        maxlength={MAX_MESSAGE_BODY}
        {placeholder}
        aria-label="message"
        onkeydown={onKeydown}
        oninput={() => {
          resize();
          refreshToken();
        }}
        onclick={refreshToken}
        onblur={() => {
          setTimeout(closeToken, 150); // no-poll (b): one-shot blur deadline; no state request
        }}></textarea>
      <button
        id="send"
        class="primary min-h-11 self-end disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
        type="button"
        disabled={uploading ||
          walkthrough.active ||
          (!hasLiveProcess && Boolean(draft.text.trim())) ||
          (!pendingFiles.files.length && !draft.text.trim())}
        onclick={() => void send()}>{uploading ? "uploading…" : "send"}</button
      >
    </div>
  </div>
  <ComposerHint attached={hasLiveProcess} length={draft.text.length} />
</ComposerDropZone>
