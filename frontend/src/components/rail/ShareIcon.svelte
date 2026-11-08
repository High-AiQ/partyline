<script lang="ts">
  import type { ShareIndicator } from "../../lib/screen-api";
  import { tooltip } from "../../lib/tooltip";
  let { indicators }: { indicators: ShareIndicator[] } = $props();
  const label = $derived(indicators.map((item) => item.label).join("; "));
</script>

{#if indicators.length}
  <span
    class="share-icon inline-flex flex-none items-center text-green"
    role="img"
    aria-label={label}
    use:tooltip={{ label }}
  >
    <svg
      viewBox="0 0 16 16"
      width="13"
      height="13"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      aria-hidden="true"
    >
      <rect x="1.5" y="2.5" width="13" height="8.5" rx="1" /><path
        d="M5.5 14h5M8 11v3"
        stroke-linecap="round"
      />
    </svg>
  </span>
{/if}
