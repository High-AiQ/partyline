<script lang="ts">
  /**
   * Archived lines: out of the way, but recoverable.
   *
   * Loaded on first open rather than with the rail — most sessions never touch
   * it, and it is the one list that grows without bound.
   */
  import { ApiError, api } from "../../lib/api";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";

  interface Props {
    onpurge: (conversation: Conversation) => void;
  }

  let { onpurge }: Props = $props();

  let loading = $state(false);
  let failed = $state(false);
  /** The id being restored, so only its own button says "restoring…". */
  let restoring = $state<string | null>(null);

  async function load(): Promise<void> {
    loading = true;
    failed = false;
    try {
      await room.loadArchived();
    } catch {
      failed = true;
    } finally {
      loading = false;
    }
  }

  function onToggle(event: Event): void {
    if (!(event.currentTarget instanceof HTMLDetailsElement)) return;
    room.archiveOpen = event.currentTarget.open;
    if (room.archiveOpen) void load();
  }

  async function restore(conversation: Conversation): Promise<void> {
    restoring = conversation.id;
    try {
      const restored = await api.restoreConversation(conversation.id);
      await room.loadConversations();
      await load();
      void room.open(restored);
    } catch (error: unknown) {
      room.showNotice(error instanceof ApiError ? error.message : "could not restore line", "error");
    } finally {
      restoring = null;
    }
  }
</script>

<details
  id="archiveSection"
  class="max-h-[30%] overflow-y-auto border-t border-dashed border-line text-cream-faint"
  ontoggle={onToggle}
>
  <summary
    class="cursor-pointer list-none px-5 py-2.5 text-[10.5px] tracking-[0.05em] hover:bg-ink-3 hover:text-cream-dim"
  >
    archived lines
    <span id="archiveCount" class="text-[10px] text-cream-faint"
      >{room.archived.length ? `(${String(room.archived.length)})` : ""}</span
    >
  </summary>
  <nav id="archivedConvs" class="px-3 pb-2" aria-label="archived lines">
    {#if loading}
      <div class="archive-note px-2 pb-1.5 text-[10px] italic text-cream-faint">loading…</div>
    {:else if failed}
      <div class="archive-note px-2 pb-1.5 text-[10px] italic text-cream-faint">
        could not load the archive
      </div>
    {:else if !room.archived.length}
      <div class="archive-note px-2 pb-1.5 text-[10px] italic text-cream-faint">no archived lines</div>
    {:else}
      {#each room.archived as conversation (conversation.id)}
        <div
          class="archive-row mb-[3px] flex items-center gap-[7px] rounded border border-cream-faint/45 p-[5px] px-2 text-cream-faint"
        >
          <span class="name min-w-0 flex-1 truncate text-[10.5px]" title={conversation.name}
            >{conversation.name}</span
          >
          <div class="archive-actions flex shrink-0 gap-1">
            <button
              type="button"
              class="restore border-green/35 px-1.5 py-1 text-[9.5px] text-green"
              title="restore this line"
              disabled={restoring === conversation.id}
              onclick={() => restore(conversation)}
              >{restoring === conversation.id ? "restoring…" : "restore"}</button
            >
            <button
              type="button"
              class="purge border-red/35 px-1.5 py-1 text-[9.5px] text-red"
              title="permanently delete this line"
              onclick={() => {
                onpurge(conversation);
              }}>delete forever</button
            >
          </div>
        </div>
      {/each}
    {/if}
  </nav>
</details>

<style>
  /* The ▸/▾ disclosure marker and the vendor details-marker reset are
       pseudo-elements Tailwind has no clean spelling for. */
  summary::-webkit-details-marker {
    display: none;
  }
  summary::before {
    content: "▸";
    display: inline-block;
    width: 14px;
    color: var(--color-cream-faint);
  }
  #archiveSection[open] summary::before {
    content: "▾";
  }
</style>
