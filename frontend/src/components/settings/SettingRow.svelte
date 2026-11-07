<script lang="ts">
  /**
   * One setting: label and description on the left, its control on the right
   * (stacked on a phone). The id is the search target, so a result can scroll
   * here and focus the control.
   */
  import type { Snippet } from "svelte";

  interface Props {
    id: string;
    label: string;
    description?: string;
    /** The control's id, so the label is a real <label for>. Omit for groups. */
    control?: string;
    /** Put the control under the text at every width (wide inputs, lists). */
    stacked?: boolean;
    children: Snippet;
    status?: Snippet;
  }

  let { id, label, description = "", control, stacked = false, children, status }: Props = $props();
</script>

<div
  {id}
  class="setting-row grid min-w-0 scroll-mt-4 gap-x-6 gap-y-2.5 rounded-md border border-line bg-ink-2/70 px-4 py-3.5 {stacked
    ? 'grid-cols-1'
    : 'grid-cols-1 min-[640px]:grid-cols-[minmax(0,1fr)_auto] min-[640px]:items-center'}"
>
  <div class="min-w-0">
    {#if control}
      <label for={control} class="block text-[12.5px] text-cream">{label}</label>
    {:else}
      <h3 class="text-[12.5px] font-normal text-cream">{label}</h3>
    {/if}
    {#if description}<p class="mt-1 text-[11px] leading-[1.5] text-cream-dim">{description}</p>{/if}
  </div>
  <div class="min-w-0">{@render children()}</div>
  {#if status}<div class="min-w-0 {stacked ? '' : 'min-[640px]:col-span-2'}">{@render status()}</div>{/if}
</div>

<style>
  /* A search result lands here: say so for a moment without moving anything. */
  .setting-row:global(.flash) {
    animation: setting-flash 1.6s ease;
  }
  @keyframes setting-flash {
    from {
      border-color: var(--color-copper);
      box-shadow: 0 0 0 3px rgb(217 142 74 / 0.25);
    }
  }
</style>
