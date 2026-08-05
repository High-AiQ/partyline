<script>
  /**
   * Archived lines: out of the way, but recoverable.
   *
   * Loaded on first open rather than with the rail — most sessions never touch
   * it, and it is the one list that grows without bound.
   */
  import { room } from "../../state/room.svelte.js";
  import { ApiError, api } from "../../lib/api.js";

  let { onpurge } = $props();

  let loading = $state(false);
  let failed = $state(false);
  /** The id being restored, so only its own button says "restoring…". */
  let restoring = $state(null);

  async function load() {
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

  function onToggle(event) {
    room.archiveOpen = event.currentTarget.open;
    if (room.archiveOpen) load();
  }

  async function restore(conversation) {
    restoring = conversation.id;
    try {
      const restored = await api.restoreConversation(conversation.id);
      await room.loadConversations();
      await load();
      room.open(restored);
    } catch (error) {
      room.showNotice(error instanceof ApiError ? error.message : "could not restore line", "error");
    } finally {
      restoring = null;
    }
  }
</script>

<details id="archiveSection" ontoggle={onToggle}>
  <summary>
    archived lines
    <span id="archiveCount">{room.archived.length ? `(${room.archived.length})` : ""}</span>
  </summary>
  <nav id="archivedConvs" aria-label="archived lines">
    {#if loading}
      <div class="archive-note">loading…</div>
    {:else if failed}
      <div class="archive-note">could not load the archive</div>
    {:else if !room.archived.length}
      <div class="archive-note">no archived lines</div>
    {:else}
      {#each room.archived as conversation (conversation.id)}
        <div class="archive-row">
          <span class="name" title={conversation.name}>{conversation.name}</span>
          <div class="archive-actions">
            <button
              type="button"
              class="restore"
              title="restore this line"
              disabled={restoring === conversation.id}
              onclick={() => restore(conversation)}
            >{restoring === conversation.id ? "restoring…" : "restore"}</button>
            <button
              type="button"
              class="purge"
              title="permanently delete this line"
              onclick={() => onpurge(conversation)}
            >delete forever</button>
          </div>
        </div>
      {/each}
    {/if}
  </nav>
</details>

<style>
  #archiveSection {
    border-top: 1px dashed var(--color-line);
    max-height: 30%;
    overflow-y: auto;
    color: var(--color-cream-faint);
  }
  summary { list-style: none; cursor: pointer; padding: 10px 20px; font-size: 10.5px; letter-spacing: 0.05em; }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "▸"; display: inline-block; width: 14px; color: var(--color-cream-faint); }
  #archiveSection[open] summary::before { content: "▾"; }
  summary:hover { color: var(--color-cream-dim); background: var(--color-ink-3); }

  #archiveCount { color: var(--color-cream-faint); font-size: 10px; }
  #archivedConvs { padding: 0 12px 8px; }

  .archive-note { padding: 0 8px 6px; font-size: 10px; font-style: italic; color: var(--color-cream-faint); }
  .archive-row {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 8px;
    margin-bottom: 3px;
    border: 1px solid rgb(93 91 82 / 0.45);
    border-radius: 4px;
    color: var(--color-cream-faint);
  }
  .name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10.5px; }
  .archive-actions { display: flex; gap: 4px; flex: none; }
  .archive-actions button { padding: 4px 6px; font-size: 9.5px; }
  .restore { color: var(--color-green); border-color: rgb(127 176 105 / 0.35); }
  .purge { color: var(--color-red); border-color: rgb(201 111 90 / 0.35); }
</style>
