<script lang="ts">
  /**
   * Start a stopped jack over: same handle, same adapter, command and cwd,
   * but a brand-new CLI session and an unread cursor at now. The old card
   * goes away when the replacement spawns; if spawning fails it stays, so a
   * failed refresh never loses the resumable session.
   */
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { attachmentLifecycleApi } from "../../lib/attachment-lifecycle-api";
  import { buildFreshRequest } from "../../lib/fresh-request";
  import type { Attachment } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    attachment: Attachment;
    close: () => void;
  }

  let { attachment, close }: Props = $props();

  let checkpoint = $state("");
  let afterMessageId = $state("");
  let starting = $state(false);
  let error = $state("");
  let field = $state<HTMLInputElement | null>(null);

  $effect(() => {
    field?.focus();
  });

  async function start(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const outcome = buildFreshRequest(checkpoint, afterMessageId);
    if (!outcome.ok) {
      error = outcome.error;
      return;
    }
    starting = true;
    error = "";
    try {
      const replacement = await attachmentLifecycleApi.fresh(attachment.id, outcome.request);
      // Same reasoning as attach and resume: the REST answer is the only news
      // we get if the socket is mid-reconnect, and the old card is gone either
      // way — the server retired it before answering. Unless the user has
      // since walked to another line: then this roster is not the one shown.
      if (room.conversation?.id === replacement.conv_id) {
        room.removeAttachment(attachment.id);
        room.upsertAttachment(replacement);
      }
      close();
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not start fresh";
      starting = false;
    }
  }
</script>

<Modal title="start fresh · {attachment.name}" {close}>
  <p class="dialog-text">
    Starts a new session under the same handle with the same command and directory. The new process receives
    the join briefing and the line topic, not the earlier chat. Give it a checkpoint to read and the last
    message id the old process incorporated; anything posted after that id is delivered on its next @mention,
    so it waits for that before resuming work. Old checkpoints may be refused to keep the new context small.
    Leave both blank for a clean start.
  </p>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
  <form class="line-form" onsubmit={start}>
    <label for="freshCheckpoint">checkpoint (optional) — a path or one continuation instruction</label>
    <input
      id="freshCheckpoint"
      bind:this={field}
      bind:value={checkpoint}
      autocomplete="off"
      spellcheck="false"
      placeholder="docs/agent-checkpoints/<book>/<task>.md"
    />
    <label for="freshAfterMessage">
      last message id the outgoing process incorporated (optional) — later ones arrive on its next mention
    </label>
    <input
      id="freshAfterMessage"
      bind:value={afterMessageId}
      autocomplete="off"
      spellcheck="false"
      inputmode="numeric"
      placeholder="blank = start at now"
    />
    <div class="line-actions">
      <button type="button" onclick={close}>cancel</button>
      <button class="primary" type="submit" disabled={starting}>
        {starting ? "starting…" : "start fresh"}
      </button>
    </div>
  </form>
</Modal>
