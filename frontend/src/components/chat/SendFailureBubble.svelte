<script lang="ts">
  /**
   * The note above the composer when a send could not be delivered. It can
   * always be dismissed; a held walkthrough take also offers retry and discard.
   */
  import ComposerBubble from "./ComposerBubble.svelte";
  import { sendFailures, type SendFailure } from "../../state/send-failures.svelte.js";

  let {
    failure,
    line,
    onretry,
    ondiscard,
  }: { failure: SendFailure; line: string | undefined; onretry: () => void; ondiscard: () => void } =
    $props();
  const dismiss = (): void => {
    if (line) sendFailures.dismiss(line);
  };
</script>

<ComposerBubble>
  <span class="flex flex-wrap items-center gap-x-2 gap-y-1" data-send-failure>
    {#if failure.message}
      <span role="alert" class="text-red">{failure.message}</span>
    {:else}
      <span role="status" class="text-cream-dim">walkthrough not sent</span>
    {/if}
    {#if failure.take}
      <button type="button" class="px-1.5 py-0.5 text-[11px]" onclick={onretry}>retry</button>
      <button type="button" class="px-1.5 py-0.5 text-[11px]" onclick={ondiscard}>discard</button>
    {/if}
    {#if failure.message}
      <button
        type="button"
        class="border-0 bg-transparent px-1 py-0 text-cream-faint hover:text-cream"
        aria-label="dismiss"
        onclick={dismiss}>✕</button
      >
    {/if}
  </span>
</ComposerBubble>
