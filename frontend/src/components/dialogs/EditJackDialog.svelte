<script lang="ts">
  /** Change what a stopped jack will launch without discarding its session. */
  import Modal from "../Modal.svelte";
  import { formatCommand } from "../../lib/attachments";
  import { ApiError, api } from "../../lib/api";
  import type { Attachment } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    attachment: Attachment;
    close: () => void;
  }

  let { attachment, close }: Props = $props();

  /* svelte-ignore state_referenced_locally */
  let command = $state(formatCommand(attachment.command));
  let saving = $state(false);
  let error = $state("");
  let field = $state<HTMLInputElement | null>(null);

  $effect(() => {
    field?.focus();
    field?.select();
  });

  async function save(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    saving = true;
    error = "";
    try {
      const updated = await api.editAttachmentCommand(attachment.id, { command });
      room.upsertAttachment(updated);
      close();
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not save command";
      saving = false;
    }
  }
</script>

<Modal title="edit command · {attachment.name}" {close}>
  <p class="dialog-text">
    This changes the command used on the next resume. The existing session and unread-message cursor stay with
    this jack.
  </p>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
  <form class="line-form" onsubmit={save}>
    <label for="editJackCommand">command (blank = adapter default)</label>
    <input
      id="editJackCommand"
      bind:this={field}
      bind:value={command}
      autocomplete="off"
      spellcheck="false"
    />
    <div class="line-actions">
      <button type="button" onclick={close}>cancel</button>
      <button class="primary" type="submit" disabled={saving}>
        {saving ? "saving…" : "save command"}
      </button>
    </div>
  </form>
</Modal>
