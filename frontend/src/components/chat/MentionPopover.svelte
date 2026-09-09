<script lang="ts">
  /** The @ autocomplete list. Keyboard handling lives in the composer, which
   *  owns the textarea; this only draws and reports clicks. */
  import { hue } from "../../lib/markdown";
  import type { MentionCandidate } from "../../lib/mentions";

  interface Props {
    candidates: MentionCandidate[];
    selected: number;
    onpick: (_index: number) => void;
    /** The operator typed `@!`: this list is choosing who to interrupt. */
    bang?: boolean;
  }

  let { candidates, selected, onpick, bang = false }: Props = $props();

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

  /** What choosing this row would actually do, said in the row itself.
   *  Not named `effect`: a `$`-prefixed local shadows the `$effect` rune. */
  const outcome = (candidate: MentionCandidate): string =>
    candidate.interruptible ? "interrupt & send" : "delivers normally";

  // A banner promising to stop a turn above a list of rows that all say
  // "delivers normally" is a lie the screenshot caught. Say which case it is.
  const anyInterruptible = $derived(candidates.some((candidate) => candidate.interruptible));
  const banner = $derived(
    anyInterruptible
      ? "Interrupt & send — stops the running turn"
      : "Interrupt & send — none of these can be interrupted",
  );
</script>

<div
  id="mentionPop"
  bind:this={list}
  role="listbox"
  aria-label="mention someone on the line"
  class="pop absolute bottom-[calc(100%+6px)] left-7 z-20 min-w-[230px] max-h-60 overflow-y-auto rounded-md border bg-ink-2 p-[5px] shadow-[0_14px_40px_rgb(0_0_0/0.5)] animate-[arrive_0.14s_ease_both]"
  class:interrupting={bang}
  class:border-line={!bang}
>
  {#if bang}
    <p
      class="banner m-0 mb-[5px] rounded px-2.5 py-1 text-[9.5px] font-semibold tracking-[0.06em] uppercase"
      class:none={!anyInterruptible}
    >
      {banner}
    </p>
  {/if}
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
        style:color={candidate.all ? "var(--color-copper)" : null}
        >{bang ? outcome(candidate) : candidate.kind}</span
      >
    </button>
  {/each}
</div>

<style>
  /* A bang is destructive, so the list says so before Enter is pressed:
     a copper frame, one short rattle on open, and per-row wording that
     distinguishes "interrupt & send" from "delivers normally". */
  .pop.interrupting {
    border-color: var(--color-copper);
    animation:
      arrive 0.14s ease both,
      rattle 0.32s ease-in-out 0.14s 1;
  }

  .banner {
    background: rgb(242 176 107 / 0.14);
    color: var(--color-copper-hot);
  }

  /* Nothing here can be stopped, so the frame should not shout as if it can. */
  .banner.none {
    background: rgb(255 255 255 / 0.05);
    color: var(--color-cream-faint);
  }

  @keyframes rattle {
    0%,
    100% {
      transform: translateX(0);
    }
    20% {
      transform: translateX(-3px);
    }
    45% {
      transform: translateX(3px);
    }
    70% {
      transform: translateX(-2px);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .pop.interrupting {
      animation: none;
    }
  }
</style>
