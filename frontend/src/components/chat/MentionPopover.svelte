<script>
  /** The @ autocomplete list. Keyboard handling lives in the composer, which
   *  owns the textarea; this only draws and reports clicks. */
  import { hue } from "../../lib/markdown.js";

  let { candidates, selected, onpick } = $props();

  let list = $state(null);

  $effect(() => {
    selected;
    list?.querySelector(".opt.sel")?.scrollIntoView({ block: "nearest" });
  });
</script>

<div id="mentionPop" bind:this={list} role="listbox" aria-label="mention someone on the line">
  {#each candidates as candidate, index (candidate.name)}
    <!-- A button, so it is an activatable control rather than a div that
         happens to listen for clicks. Arrow-key navigation lives in the
         composer, which owns the caret and must keep focus. `mousedown` is
         suppressed for the same reason: clicking must not blur the textarea. -->
    <button
      type="button"
      class="opt"
      class:sel={index === selected}
      role="option"
      aria-selected={index === selected}
      tabindex="-1"
      onmousedown={(event) => event.preventDefault()}
      onclick={() => onpick(index)}
    >
      <span class="led {candidate.status ?? ''}" class:blank={!candidate.status}></span>
      <span class="nm" style:color={candidate.all ? "var(--color-copper-hot)" : `hsl(${hue(candidate.name.toLowerCase())} 55% 68%)`}>
        @{candidate.name}
      </span>
      <span class="kind" style:color={candidate.all ? "var(--color-copper)" : null}>{candidate.kind}</span>
    </button>
  {/each}
</div>

<style>
  #mentionPop {
    position: absolute;
    bottom: calc(100% + 6px);
    left: 28px;
    z-index: 20;
    background: var(--color-ink-2);
    border: 1px solid var(--color-line);
    border-radius: 6px;
    min-width: 230px;
    max-height: 240px;
    overflow-y: auto;
    padding: 5px;
    box-shadow: 0 14px 40px rgb(0 0 0 / 0.5);
    animation: arrive 0.14s ease both;
  }
  .opt {
    /* a button, styled back down to the row it reads as */
    background: none;
    border: 0;
    width: 100%;
    text-align: left;
    font: inherit;
    letter-spacing: normal;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 10px;
    border-radius: 4px;
    cursor: pointer;
    color: var(--color-cream-dim);
  }
  .opt .led { width: 6px; height: 6px; }
  .opt .led.blank { background: none; }
  .nm { font-weight: 600; flex: 1; }
  .kind { font-size: 9.5px; color: var(--color-cream-faint); letter-spacing: 0.06em; }
  .opt:hover, .opt.sel { background: var(--color-ink-3); color: var(--color-cream); }
</style>
