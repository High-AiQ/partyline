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
  // This describes the registry now, not the adapter class used when an
  // already-running jack was created; reload can change one without the other.
  const overridesBundled = (adapterId: string): boolean =>
    session.adapters.find((adapter) => adapter.id === adapterId)?.overrides_bundled ?? false;
</script>

<aside id="board" class="bg-ink-2 border-l border-line flex flex-col overflow-y-auto">
  <h2 class="font-serif italic font-normal text-[17px] text-cream-dim px-[18px] pt-5 pb-2.5">on the line</h2>
  <div id="jacks" class="px-3 pb-2">
    {#if !jacks.length}
      <div class="note px-2 text-[11px] italic text-cream-faint">nobody attached yet</div>
    {:else}
      {#each jacks as attachment (attachment.id)}
        <JackCard
          {attachment}
          resumable={canResumeJack(session.adapters, attachment)}
          overridesBundled={overridesBundled(attachment.adapter)}
          {onmention}
        />
      {/each}
    {/if}
  </div>

  <h3 class="font-serif italic font-normal text-[17px] text-cream-dim px-[18px] pt-5 pb-2.5">
    patch in a process
  </h3>
  <AttachForm />
</aside>
