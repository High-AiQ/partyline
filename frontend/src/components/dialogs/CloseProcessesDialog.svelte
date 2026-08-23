<script lang="ts">
  /** Confirm and detach every currently live process while preserving the line. */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api";
  import { isLive } from "../../lib/attachments";
  import type { Attachment, Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }

  let { conversation, close }: Props = $props();
  let loading = $state(true);
  let failed = $state(false);
  let live = $state<Attachment[]>([]);

  $effect(() => {
    api
      .conversation(conversation.id)
      .then((detail) => {
        live = detail.attachments.filter(isLive);
      })
      .catch(() => {
        failed = true;
      })
      .finally(() => {
        loading = false;
      });
  });

  async function closeProcesses(): Promise<void> {
    const result = await api.closeProcesses(conversation.id);
    close();
    await room.loadConversations();
    room.showNotice(
      result.stopped.length
        ? `closed ${String(result.stopped.length)} process${result.stopped.length === 1 ? "" : "es"} on ${conversation.name}`
        : `no live processes on ${conversation.name}`,
    );
  }
</script>

<Modal title="close processes · {conversation.name}" {close}>
  {#if loading}
    <p class="dialog-text">Loading the line’s live processes…</p>
  {:else if failed}
    <p class="line-status error" role="alert">Could not load this line. Try again.</p>
  {:else}
    <p class="dialog-text">Detaches every live process on this line. The line and its history stay.</p>

    <div class="live-list">
      {#if live.length}
        <div class="dialog-note">processes to close</div>
        {#each live as attachment (attachment.id)}
          <div class="live-item"><span class="led running"></span><span>@{attachment.name}</span></div>
        {/each}
      {:else}
        <div class="dialog-note">no live processes are attached</div>
      {/if}
    </div>

    <ConfirmForm
      phrase={live.length ? conversation.name : null}
      prompt="type the line name to confirm"
      label="close processes"
      busyLabel="closing…"
      onconfirm={closeProcesses}
      oncancel={close}
    />
  {/if}
</Modal>
