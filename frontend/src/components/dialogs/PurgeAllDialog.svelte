<script lang="ts">
  /** Delete every archived line for good. Cannot be undone. */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    conversations: Conversation[];
    close: () => void;
  }

  let { conversations, close }: Props = $props();

  async function purge(): Promise<void> {
    const result = await api.purgeArchivedConversations();
    close();
    await room.loadArchived();
    const count = result.purged.length;
    const skipped = result.skipped.length;
    const toast =
      skipped > 0
        ? `purged ${String(count)} line${count === 1 ? "" : "s"}, ${String(skipped)} skipped`
        : `purged ${String(count)} line${count === 1 ? "" : "s"}`;
    room.showNotice(toast);
  }
</script>

<Modal title="purge all archived lines" {close}>
  <p class="dialog-text">
    Messages, files, and worktrees are deleted and cannot be undone. Permanently delete {conversations.length} archived
    line{conversations.length === 1 ? "" : "s"}?
  </p>
  <div class="dialog-note mb-1 text-[11px] text-cream-faint">
    {conversations.length} archived line{conversations.length === 1 ? "" : "s"}:
  </div>
  <ul class="max-h-36 overflow-y-auto rounded border border-line bg-ink-3 p-2 text-[12px] text-cream-dim">
    {#each conversations as conv (conv.id)}
      <li class="truncate py-0.5">{conv.name}</li>
    {/each}
  </ul>
  <ConfirmForm
    phrase={null}
    prompt=""
    label="purge all"
    busyLabel="purging…"
    onconfirm={purge}
    oncancel={close}
  />
</Modal>
