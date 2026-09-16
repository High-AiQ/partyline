<script lang="ts">
  /**
   * Delete a line, and stop whatever is running on it.
   *
   * The warning button is the reason this dialog is not a `confirm()`: an agent
   * mid-task loses uncommitted work when its line goes, and it can only save
   * that work if somebody tells it to first.
   */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { ApiError, api } from "../../lib/api";
  import { isLive } from "../../lib/attachments";
  import type { Attachment, Conversation } from "../../lib/contracts";
  import { descendantLineIds } from "../../lib/line-hierarchy";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }

  let { conversation, close }: Props = $props();

  let loading = $state(true);
  let failed = $state(false);
  let live = $state<Attachment[]>([]);

  let warning = $state(false);
  let warned = $state(false);
  let warnError = $state("");
  // Child lines cannot be left behind by an archived parent, so a root with
  // children offers the whole tree in one checkbox instead of a refusal.
  const childIds = $derived(descendantLineIds(conversation.id, room.conversations));
  let includeChildren = $state<boolean>(false);

  $effect(() => {
    const targetIds = includeChildren ? [conversation.id, ...childIds] : [conversation.id];
    Promise.all(targetIds.map((id) => api.conversation(id)))
      .then((details) => {
        live = details.flatMap((detail) => detail.attachments.filter(isLive));
      })
      .catch(() => {
        failed = true;
      })
      .finally(() => {
        loading = false;
      });
  });

  async function warn() {
    warning = true;
    warnError = "";
    try {
      await room.warn(
        conversation.id,
        "@all this line is being deleted soon. Please commit your work and post status.",
      );
      warned = true;
    } catch (error: unknown) {
      warnError = error instanceof ApiError ? error.message : "could not send warning";
    } finally {
      warning = false;
    }
  }

  async function remove() {
    const result = await api.archiveConversation(conversation.id, includeChildren);
    close();
    if (room.conversation?.id === conversation.id) room.leave();
    await room.loadConversations();
    room.refreshArchiveIfOpen();
    let message = "line deleted";
    if (result.worktree_kept_reason) message += `; its worktree was kept (${result.worktree_kept_reason})`;
    else if (result.worktree_removed) message += "; its worktree was removed";
    room.showNotice(message);
  }
</script>

<Modal title="delete line · {conversation.name}" {close}>
  {#if loading}
    <p class="dialog-text">Loading the line’s live processes…</p>
  {:else if failed}
    <p class="line-status error">Could not load this line. Try again.</p>
  {:else}
    <p class="dialog-text">
      Deleting this line removes it from the sidebar and stops its attached processes.
    </p>

    {#if childIds.length}
      <label class="dialog-check">
        <input type="checkbox" bind:checked={includeChildren} />
        also delete its {childIds.length} child line{childIds.length === 1 ? "" : "s"} and stop their processes
      </label>
      {#if !includeChildren}
        <div class="dialog-note">child lines must be deleted or unlinked first</div>
      {/if}
    {/if}

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
      phrase={conversation.name}
      prompt="type the line name to confirm"
      label="delete line"
      busyLabel="removing…"
      onconfirm={remove}
      oncancel={close}
    />
  {/if}
</Modal>
