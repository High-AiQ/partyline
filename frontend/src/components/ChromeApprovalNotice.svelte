<script lang="ts">
  /**
   * A non-modal reminder while Chrome waits for the person to click its own Allow prompt in a window
   * shared with this line. It goes away on its own when the prompt is answered or the share ends.
   */
  import { chromeApproval } from "../state/chrome-approval.svelte.js";
  import { memoryRequest } from "../state/memory-request.svelte.js";
  import { restart } from "../state/restart.svelte.js";
  import { room } from "../state/room.svelte.js";
  import { writeSet } from "../state/write-set.svelte.js";

  const notices = $derived(chromeApproval.forLine(room.conversation?.id));
  // Sit under whichever request banners are up, so none covers another.
  const top = $derived(
    memoryRequest.request
      ? "top-[126px]"
      : restart.request && writeSet.request
        ? "top-[90px]"
        : restart.request || writeSet.request
          ? "top-[54px]"
          : "top-[18px]",
  );
</script>

{#if notices.length}
  <div
    id="chromeApproval"
    class="fixed left-1/2 {top} z-69 flex max-w-[min(640px,92vw)] -translate-x-1/2 flex-col gap-1 rounded-[5px] border border-copper/60 bg-ink-2 px-[14px] py-2 text-[11px] text-cream-dim shadow-[0_12px_30px_rgb(0_0_0/0.45)]"
    role="status"
    aria-live="polite"
  >
    {#each notices as notice (notice.grant_id)}
      <span class="min-w-0 whitespace-normal break-words"
        >Chrome is waiting for you to click Allow in the shared window ({notice.title})</span
      >
    {/each}
  </div>
{/if}
