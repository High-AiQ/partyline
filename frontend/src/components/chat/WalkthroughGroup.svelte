<script lang="ts">
  /** The strip a walkthrough shows from the moment it begins until it is sent or gone. */
  import { stageText, type WalkthroughStage } from "../../lib/walkthrough-status";
  import type { WalkthroughMic } from "../../state/walkthrough-mic.svelte.js";
  import MicLevel from "./MicLevel.svelte";

  let {
    stage,
    elapsed,
    mic,
    mark = $bindable(false),
    onstop,
    oncancel,
  }: {
    stage: WalkthroughStage;
    elapsed: number;
    mic: WalkthroughMic;
    mark?: boolean;
    onstop: () => void;
    oncancel: () => void;
  } = $props();
</script>

<div
  class="order-last flex basis-full flex-wrap items-center gap-2 border-t border-line pt-2 text-sm"
  role="group"
  aria-label="Walkthrough"
>
  <span role="status">{stageText(stage, elapsed)}</span>
  {#if stage === "recording"}
    <MicLevel level={mic.level} label={mic.label} named wide />
    {#if mic.silent}<span class="text-red" role="alert">no input detected — is the mic muted?</span>{/if}
  {/if}
  {#if mic.notice}<span role="status">{mic.notice}</span>{/if}
  {#if stage === "recording"}<button type="button" onclick={onstop}>Stop and send</button>{/if}
  <button type="button" onclick={oncancel}>Cancel</button>
  <label><input type="checkbox" bind:checked={mark} /> Mark pointer</label>
</div>
