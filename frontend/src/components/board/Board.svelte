<script lang="ts">
  /** The right rail: who is on the line, and how to patch someone in. */
  import JackCard from "./JackCard.svelte";
  import AttachForm from "./AttachForm.svelte";
  import { canResumeJack, latestJacks } from "../../lib/attachments";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";

  interface Props {
    onmention: (_name: string) => void;
  }

  let { onmention }: Props = $props();

  const jacks = $derived(latestJacks(room.attachments));
</script>

<aside id="board">
  <h2>on the line</h2>
  <div id="jacks">
    {#if !jacks.length}
      <div class="note">nobody attached yet</div>
    {:else}
      {#each jacks as attachment (attachment.id)}
        <JackCard {attachment} resumable={canResumeJack(session.adapters, attachment)} {onmention} />
      {/each}
    {/if}
  </div>

  <h3>patch in a process</h3>
  <AttachForm />
</aside>

<style>
  #board {
    background: var(--color-ink-2);
    border-left: 1px solid var(--color-line);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }
  h2,
  h3 {
    font-family: var(--font-serif);
    font-style: italic;
    font-weight: 400;
    font-size: 17px;
    color: var(--color-cream-dim);
    padding: 20px 18px 10px;
  }
  #jacks {
    padding: 0 12px 8px;
  }
  .note {
    padding: 0 8px;
    color: var(--color-cream-faint);
    font-size: 11px;
    font-style: italic;
  }
</style>
