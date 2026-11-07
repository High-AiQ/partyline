<script lang="ts">
  /**
   * A transient note floating above the composer. It anchors to the composer
   * (the nearest positioned ancestor), not to the icon that raised it, so its
   * width is bounded by the composer's own gutters at any viewport.
   */
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();
</script>

<div
  class="absolute bottom-full left-3 z-10 mb-1 w-fit max-w-[calc(100%-1.5rem)] min-w-0 rounded border border-line bg-ink-2 px-2 py-1 text-[11px] break-words min-[900px]:left-7 min-[900px]:max-w-[calc(100%-3.5rem)]"
  data-composer-bubble
>
  {@render children()}
</div>
