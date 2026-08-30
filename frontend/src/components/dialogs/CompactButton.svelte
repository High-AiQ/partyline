<script lang="ts">
  import { ApiError, api } from "../../lib/api";

  interface Props {
    attachmentId: string;
  }

  let { attachmentId }: Props = $props();
  let busy = $state(false);
  let status = $state("");

  async function compact(): Promise<void> {
    busy = true;
    status = "";
    try {
      const result = await api.compact(attachmentId);
      status = result.queued ? "queued for turn end" : "compact command sent";
    } catch (error) {
      status = error instanceof ApiError ? error.message : "could not compact this process";
    } finally {
      busy = false;
    }
  }
</script>

<button type="button" onclick={compact} disabled={busy}>{busy ? "sending…" : "compact"}</button>
{#if status}
  <!-- Parity note: the pre-migration `.error` rule referenced an undefined
       `--color-danger` token and never applied; failure text has always
       rendered cream-faint. Fixing that is a separate change. -->
  <span class="text-cream-faint text-[10.5px]" aria-live="polite">{status}</span>
{/if}
