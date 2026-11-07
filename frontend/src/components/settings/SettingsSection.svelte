<script lang="ts">
  /** One settings section: its serif title, a one-line blurb, then its rows. */
  import type { Snippet } from "svelte";
  import { sectionInfo } from "../../lib/settings-registry";
  import type { SectionId } from "../../lib/settings-route";

  interface Props {
    id: SectionId;
    children: Snippet;
    actions?: Snippet;
  }

  let { id, children, actions }: Props = $props();
  const info = $derived(sectionInfo(id));
</script>

<section class="flex min-w-0 flex-col gap-4" aria-labelledby="settings-heading-{id}">
  <header class="flex flex-wrap items-end justify-between gap-3 border-b border-dashed border-line pb-3">
    <div class="min-w-0">
      <h2
        id="settings-heading-{id}"
        tabindex="-1"
        class="font-serif text-[28px] leading-none font-normal text-cream italic outline-none"
      >
        {info.label}
      </h2>
      <p class="mt-1.5 text-[11px] text-cream-dim">{info.blurb}</p>
    </div>
    {#if actions}<div class="flex flex-wrap gap-2">{@render actions()}</div>{/if}
  </header>
  {@render children()}
</section>
