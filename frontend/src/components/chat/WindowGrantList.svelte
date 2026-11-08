<script lang="ts">
  import { screenApi, type ScreenWindowGrant } from "../../lib/screen-api";
  let { grants, refresh }: { grants: ScreenWindowGrant[]; refresh: () => Promise<void> } = $props();
  let error = $state("");
  async function stop(id: string): Promise<void> {
    try {
      await screenApi.revokeWindow(id);
      await refresh();
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not stop window sharing";
    }
  }
</script>

{#if grants.length}
  <ul class="flex flex-col gap-2 text-sm">
    {#each grants as grant (grant.id)}
      <li class="flex flex-wrap items-center gap-2">
        <span>{grant.title} → @{grant.holder} on «{grant.line_name}»</span>
        <button type="button" onclick={() => void stop(grant.id)}>Stop sharing window</button>
      </li>
    {/each}
  </ul>
{/if}
{#if error}<p role="alert">{error}</p>{/if}
