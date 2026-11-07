<script lang="ts">
  /**
   * Section links: a column on desktop, a scrolling tab strip on a phone.
   * Real links to `#/settings/<id>`, so middle-click, Back and Forward all work.
   */
  import { SECTIONS } from "../../lib/settings-registry";
  import { settingsRoute } from "../../lib/settings-route";
  import type { SectionId } from "../../lib/settings-route";

  interface Props {
    current: SectionId;
    /** Result counts while a search is active; null when not searching. */
    counts: Map<SectionId, number> | null;
    onnavigate: () => void;
  }

  let { current, counts, onnavigate }: Props = $props();
  let strip = $state<HTMLElement | null>(null);

  // Keep the active tab in view when the strip scrolls sideways on a phone.
  $effect(() => {
    const active = strip?.querySelector<HTMLElement>(`[data-section="${current}"]`);
    active?.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
</script>

<nav
  aria-label="settings sections"
  class="settings-nav min-w-0 border-b border-line min-[900px]:border-r min-[900px]:border-b-0"
>
  <ul
    bind:this={strip}
    class="flex gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none] min-[900px]:flex-col min-[900px]:gap-0.5 min-[900px]:overflow-visible min-[900px]:px-3 min-[900px]:py-4"
  >
    {#each SECTIONS as section (section.id)}
      {@const count = counts?.get(section.id) ?? 0}
      {@const active = section.id === current && !counts}
      <li class="flex-none">
        <a
          href={settingsRoute(section.id)}
          data-section={section.id}
          aria-current={active ? "page" : undefined}
          onclick={onnavigate}
          class="relative flex min-h-11 items-center justify-between gap-3 rounded px-3 text-[12px] whitespace-nowrap no-underline transition-colors min-[900px]:min-h-9 {active
            ? 'bg-ink-3 text-copper-hot'
            : 'text-cream-dim hover:bg-ink-3 hover:text-cream'} {counts && !count ? 'opacity-40' : ''}"
        >
          {#if active}<span
              class="absolute inset-x-3 bottom-0 h-0.5 rounded bg-copper min-[900px]:inset-x-auto min-[900px]:inset-y-2 min-[900px]:left-0 min-[900px]:h-auto min-[900px]:w-0.5"
              aria-hidden="true"
            ></span>{/if}
          <span>{section.label}</span>
          {#if counts && count}<span
              class="rounded-full bg-copper/20 px-1.5 text-[10px] text-copper-hot"
              aria-label="{count} matching">{count}</span
            >{/if}
        </a>
      </li>
    {/each}
  </ul>
</nav>
