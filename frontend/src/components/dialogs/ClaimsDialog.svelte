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
    <p class="py-[22px] text-cream-faint text-center italic">loading claims…</p>
  {:else if error}
    <p class="text-red" role="alert">{error}</p>
  {:else if !claims.length}
    <p class="py-[22px] text-cream-faint text-center italic">no paths claimed</p>
  {:else}
    <div class="flex flex-col gap-2">
      {#each claims as claim (claim.id)}
        <article class="px-3 py-2.5 border border-line rounded-[5px] bg-ink-3">
          <header class="flex justify-between gap-3 mb-[7px]">
            <strong class="text-copper-hot font-semibold">@{claim.owner}</strong>
            <span
              class="text-cream-faint text-[10px]"
              title={new Date(claim.expires_at * 1000).toLocaleString()}>{expires(claim.expires_at)}</span
            >
          </header>
          <ul class="flex flex-col gap-1 list-none">
            {#each claim.paths as path (path)}
              <li><code class="text-cream-dim text-[11px] wrap-anywhere">{path}</code></li>
            {/each}
          </ul>
        </article>
      {/each}
    </div>
  {/if}
</Modal>
