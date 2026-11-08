<script lang="ts">
  /** The composer's line icons, drawn once so the row and its menu cannot drift apart. */
  let { name }: { name: "attach" | "mic" | "ear" | "more" } = $props();
</script>

<svg
  class="size-[18px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
  viewBox="0 0 24 24"
  aria-hidden="true"
>
  {#if name === "attach"}
    <path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l10-10a4 4 0 1 1 5.7 5.7l-10 10a2 2 0 0 1-2.9-2.8l9.3-9.3" />
  {:else if name === "mic"}
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  {:else if name === "ear"}
    <path d="M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0" />
    <path d="M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4" />
  {:else}
    <path d="M12 5v14M5 12h14" />
  {/if}
</svg>
