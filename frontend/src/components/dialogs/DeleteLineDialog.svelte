<script>
  /**
   * Delete a line, and stop whatever is running on it.
   *
   * The warning button is the reason this dialog is not a `confirm()`: an agent
   * mid-task loses uncommitted work when its line goes, and it can only save
   * that work if somebody tells it to first.
   */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api.js";
  import { isLive } from "../../lib/attachments.js";
  import { room } from "../../state/room.svelte.js";

  let { conversation, close } = $props();

  let loading = $state(true);
  let failed = $state(false);
  let live = $state([]);

  let warning = $state(false);
  let warned = $state(false);
  let warnError = $state("");

  $effect(() => {
    api.conversation(conversation.id)
      .then((detail) => { live = (detail.attachments || []).filter(isLive); })
      .catch(() => { failed = true; })
      .finally(() => { loading = false; });
  });

  async function warn() {
    warning = true;
    warnError = "";
    try {
      await room.warn(conversation.id, "@all this line is being deleted soon. Please commit your work and post status.");
      warned = true;
    } catch (error) {
      warnError = error.message || "could not send warning";
    } finally {
      warning = false;
    }
  }

  async function remove() {
    await api.archiveConversation(conversation.id);
    close();
    if (room.conversation?.id === conversation.id) room.leave();
    await room.loadConversations();
    room.refreshArchiveIfOpen();
  }
</script>

<Modal title="delete line · {conversation.name}" {close}>
  {#if loading}
    <p class="dialog-text">Loading the line’s live processes…</p>
  {:else if failed}
    <p class="line-status error">Could not load this line. Try again.</p>
  {:else}
    <p class="dialog-text">Deleting this line removes it from the sidebar and stops its attached processes.</p>

    <div class="live-list">
      {#if live.length}
        <div class="dialog-note">running processes — warning them first is recommended</div>
        {#each live as attachment (attachment.id)}
          <div class="live-item"><span class="led running"></span><span>@{attachment.name}</span></div>
        {/each}
        <button type="button" class="primary" disabled={warning || warned} onclick={warn}>
          {warned ? "warning sent" : warning ? "sending warning…" : "warn processes first"}
        </button>
      {:else}
        <div class="dialog-note">no running processes are attached</div>
      {/if}
    </div>

    {#if warned}
      <div class="line-status warn-sent">The warning was posted to the line.</div>
    {:else if warnError}
      <div class="line-status error">{warnError}</div>
    {/if}

    <ConfirmForm
      phrase={live.length ? conversation.name : null}
      prompt="type the line name to confirm"
      label="delete line"
      busyLabel="removing…"
      onconfirm={remove}
      oncancel={close}
    />
  {/if}
</Modal>
