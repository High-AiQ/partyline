<script lang="ts">
  /** The @ autocomplete list. Keyboard handling lives in the composer, which
   *  owns the textarea; this only draws and reports clicks. */
  import { hue } from "../../lib/markdown";
  import type { MentionCandidate } from "../../lib/mentions";

  interface Props {
    candidates: MentionCandidate[];
    selected: number;
    onpick: (_index: number) => void;
  }

  let { candidates, selected, onpick }: Props = $props();

  let list = $state<HTMLDivElement | null>(null);

  $effect(() => {
    void selected;
    list?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  });

  function optionClass(isSelected: boolean): string {
    const shared =
      "opt flex w-full cursor-pointer items-center gap-[9px] rounded border-0 px-2.5 py-1.5 text-left [font:inherit] tracking-normal";
    return isSelected
      ? `${shared} bg-ink-3 text-cream`
      : `${shared} bg-transparent text-cream-dim hover:bg-ink-3 hover:text-cream`;
  }
</script>

<div
  id="mentionPop"
  bind:this={list}
  role="listbox"
  aria-label="mention someone on the line"
  class="absolute bottom-[calc(100%+6px)] left-7 z-20 min-w-[230px] max-h-60 overflow-y-auto rounded-md border border-line bg-ink-2 p-[5px] shadow-[0_14px_40px_rgb(0_0_0/0.5)] animate-[arrive_0.14s_ease_both]"
>
  {#each candidates as candidate, index (candidate.name)}
    <!-- A button, so it is an activatable control rather than a div that
         happens to listen for clicks. Arrow-key navigation lives in the
         composer, which owns the caret and must keep focus. `mousedown` is
         suppressed for the same reason: clicking must not blur the textarea. -->
    <button
      type="button"
      class={optionClass(index === selected)}
      role="option"
      aria-selected={index === selected}
      tabindex="-1"
      onmousedown={(event: MouseEvent) => {
        event.preventDefault();
      }}
      onclick={() => {
        onpick(index);
      }}
    >
      <span class="led size-[6px] {candidate.status ?? ''} {!candidate.status ? '[background:none]' : ''}"
      ></span>
      <span
        class="flex-1 font-semibold"
        style:color={candidate.all
          ? "var(--color-copper-hot)"
          : `hsl(${String(hue(candidate.name.toLowerCase()))} 55% 68%)`}
      >
        @{candidate.name}
      </span>
      <span
        class="text-[9.5px] tracking-[0.06em] text-cream-faint"
        style:color={candidate.all ? "var(--color-copper)" : null}>{candidate.kind}</span
      >
    </button>
  {/each}
</div>
