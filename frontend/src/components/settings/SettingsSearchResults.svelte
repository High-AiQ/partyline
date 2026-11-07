<script lang="ts">
  /** Matches from every section; choosing one opens its section at that row. */
  import { sectionInfo } from "../../lib/settings-registry";
  import type { SettingInfo } from "../../lib/settings-registry";

  interface Props {
    query: string;
    results: SettingInfo[];
    onpick: (_setting: SettingInfo) => void;
  }

  let { query, results, onpick }: Props = $props();
</script>

<section aria-label="search results" class="flex min-w-0 flex-col gap-3">
  <p class="text-[11px] text-cream-dim" aria-live="polite">
    {results.length
      ? `${String(results.length)} setting${results.length === 1 ? "" : "s"} match “${query.trim()}”`
      : `no settings match “${query.trim()}”`}
  </p>
  <ul class="flex flex-col gap-2">
    {#each results as result (result.id)}
      <li>
        <button
          type="button"
          class="search-result flex w-full min-w-0 flex-col items-start gap-1 rounded-md border border-line bg-ink-2/70 px-4 py-3 text-left normal-case"
          onclick={() => {
            onpick(result);
          }}
        >
          <span class="flex w-full min-w-0 items-center justify-between gap-3">
            <span class="truncate text-[12.5px] text-cream">{result.label}</span>
            <span class="flex-none text-[10px] tracking-[0.06em] text-copper uppercase"
              >{sectionInfo(result.section).label}</span
            >
          </span>
          <span class="text-[11px] leading-[1.5] text-cream-dim">{result.description}</span>
        </button>
      </li>
    {/each}
  </ul>
</section>

<style>
  /* The global button hover fills copper and recolours the text; a result card stays readable. */
  .search-result:hover {
    background: var(--color-ink-3);
    border-color: var(--color-copper);
    color: inherit;
  }
</style>
