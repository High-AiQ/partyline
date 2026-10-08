<script lang="ts">
  /**
   * Archive several lines at once.
   *
   * One typed word stands in for typing every line name: the list above the
   * form is the thing being confirmed. Exactly those lines go deepest first,
   * one at a time, never with include_children. A failure keeps the dialog
   * open, so a retry never re-sends a line that is already gone.
   */
  import { untrack } from "svelte";
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { ApiError, api } from "../../lib/api";
  import { isLive } from "../../lib/attachments";
  import type { Attachment, Conversation } from "../../lib/contracts";
  import { archiveOrder } from "../../lib/bulk-select";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    lines: Conversation[];
    close: () => void;
    ondone?: () => void;
  }

  let { lines, close, ondone }: Props = $props();

  let live = $state<Attachment[]>([]);
  const done: string[] = [];
  // Frozen when the dialog opens: the confirmed list is the whole scope.
  const order = untrack(() =>
    archiveOrder(new Set(lines.map((line) => line.id)), [...room.conversations, ...lines]),
  );

  $effect(() => {
    Promise.all(lines.map((line) => api.conversation(line.id)))
      .then((details) => {
        live = details.flatMap((detail) => detail.attachments.filter(isLive));
      })
      .catch(() => {
        live = [];
      });
  });

  async function archiveAll(): Promise<void> {
    const failures: string[] = [];
    for (const id of order) {
      if (done.includes(id)) continue;
      try {
        const result = await api.archiveConversation(id);
        done.push(id);
        const gone = result.archived_ids.length ? result.archived_ids : [id];
        if (room.conversation && gone.includes(room.conversation.id)) room.leave();
      } catch (error: unknown) {
        const name = lines.find((line) => line.id === id)?.name ?? id;
        failures.push(`${name}: ${error instanceof ApiError ? error.message : "could not archive"}`);
      }
    }
    await room.loadConversations();
    room.refreshArchiveIfOpen();
    if (failures.length) throw new Error(failures.join("; "));
    close();
    ondone?.();
    room.showNotice(`${String(lines.length)} line${lines.length === 1 ? "" : "s"} archived`);
  }
</script>

<Modal title="archive {lines.length} line{lines.length === 1 ? '' : 's'}" {close}>
  <p class="dialog-text">
    Archiving these lines removes them from the sidebar and stops their attached processes. They stay
    recoverable from the archive.
  </p>
  <div class="live-list">
    {#each lines as line (line.id)}
      <div class="live-item"><span>{line.name}</span></div>
    {/each}
  </div>
  {#if live.length}
    <div class="dialog-note">
      {live.length} running process{live.length === 1 ? "" : "es"} will be stopped:
      {live.map((attachment) => `@${attachment.name}`).join(", ")}
    </div>
  {/if}
  <ConfirmForm
    phrase="confirm"
    prompt="type confirm to archive these lines"
    label="archive lines"
    busyLabel="removing…"
    onconfirm={archiveAll}
    oncancel={close}
  />
</Modal>
