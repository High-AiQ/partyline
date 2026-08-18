<script lang="ts">
  /** Read-only ownership claims for one line. */
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { coordinationApi } from "../../lib/coordination-api";
  import type { Claim, Conversation } from "../../lib/contracts";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }

  let { conversation, close }: Props = $props();
  let claims = $state<Claim[]>([]);
  let loading = $state(true);
  let error = $state("");

  $effect(() => {
    loading = true;
    error = "";
    void coordinationApi
      .claims(conversation.id)
      .then((found) => (claims = found))
      .catch((caught: unknown) => {
        error = caught instanceof ApiError ? caught.message : "could not load claims";
      })
      .finally(() => (loading = false));
  });

  function expires(at: number): string {
    const minutes = Math.max(0, Math.ceil((at * 1000 - Date.now()) / 60_000));
    if (minutes < 60) return `${String(minutes)}m left`;
    return `${String(Math.ceil(minutes / 60))}h left`;
  }
</script>

<Modal title="claims · {conversation.name}" {close}>
  <p class="dialog-note">write ownership for this line · read-only here</p>
  {#if loading}
    <p class="empty">loading claims…</p>
  {:else if error}
    <p class="error" role="alert">{error}</p>
  {:else if !claims.length}
    <p class="empty">no paths claimed</p>
  {:else}
    <div class="claims">
      {#each claims as claim (claim.id)}
        <article>
          <header>
            <strong>@{claim.owner}</strong>
            <span title={new Date(claim.expires_at * 1000).toLocaleString()}>{expires(claim.expires_at)}</span
            >
          </header>
          <ul>
            {#each claim.paths as path (path)}
              <li><code>{path}</code></li>
            {/each}
          </ul>
        </article>
      {/each}
    </div>
  {/if}
</Modal>

<style>
  .claims {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  article {
    padding: 10px 12px;
    border: 1px solid var(--color-line);
    border-radius: 5px;
    background: var(--color-ink-3);
  }
  header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 7px;
  }
  strong {
    color: var(--color-copper-hot);
    font-weight: 600;
  }
  header span {
    color: var(--color-cream-faint);
    font-size: 10px;
  }
  ul {
    display: flex;
    flex-direction: column;
    gap: 4px;
    list-style: none;
  }
  code {
    color: var(--color-cream-dim);
    font-size: 11px;
    overflow-wrap: anywhere;
  }
  .empty {
    padding: 22px 0;
    color: var(--color-cream-faint);
    text-align: center;
    font-style: italic;
  }
  .error {
    color: var(--color-red);
  }
</style>
