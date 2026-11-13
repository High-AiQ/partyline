<script lang="ts">
  /** The quiet chain marker on a rail row: `ch N` on a continuing line, → on the line it continues. */
  import { tooltip } from "../../lib/tooltip";
  import type { ChapterMarker } from "../../lib/chapters";

  let { chain }: { chain: ChapterMarker } = $props();
</script>

{#if chain.label}<span
    class="chapter-mark flex-none text-[10px] text-cream-faint"
    use:tooltip={{ label: `continues ${chain.continuesFrom?.name ?? "an earlier chapter"}` }}
    >{chain.label}</span
  >{/if}{#if chain.continuedIn}<span
    class="chapter-next flex-none text-[10px] text-cream-faint"
    aria-label="continued in {chain.continuedIn.name}"
    use:tooltip={{ label: `continued in ${chain.continuedIn.name}` }}>→</span
  >{/if}
