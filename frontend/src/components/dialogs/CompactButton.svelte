<script lang="ts">
  import { ApiError, api } from "../../lib/api";

  interface Props {
    attachmentId: string;
  }

  let { attachmentId }: Props = $props();
  let busy = $state(false);
  let status = $state("");
  let failed = $state(false);

  async function compact(): Promise<void> {
    busy = true;
    status = "";
    failed = false;
    try {
      const result = await api.compact(attachmentId);
      status = result.queued ? "queued for turn end" : "compact command sent";
    } catch (error) {
      failed = true;
      status = error instanceof ApiError ? error.message : "could not compact this process";
    } finally {
      busy = false;
    }
  }
</script>

<button type="button" onclick={compact} disabled={busy}>{busy ? "sending…" : "compact"}</button>
{#if status}
  <span class:error={failed} class="status" aria-live="polite">{status}</span>
{/if}

<style>
  .status {
    color: var(--color-cream-faint);
    font-size: 10.5px;
  }
  .error {
    color: var(--color-danger);
  }
</style>
