<script lang="ts">
  /** Saving…, a brief "saved ✓", or the error, announced politely. */
  import type { SaveSnapshot } from "../../lib/save-state";

  interface Props {
    state: SaveSnapshot;
    idle?: string;
  }

  let { state, idle = "" }: Props = $props();
</script>

<p
  class="min-h-[18px] text-[10.5px] {state.phase === 'error'
    ? 'text-red'
    : state.phase === 'saved'
      ? 'text-green'
      : 'text-cream-faint italic'}"
  aria-live="polite"
  data-save-phase={state.phase}
>
  {#if state.phase === "saving"}saving…{:else if state.phase === "saved"}saved ✓{:else if state.phase === "error"}{state.message}{:else}{idle}{/if}
</p>
