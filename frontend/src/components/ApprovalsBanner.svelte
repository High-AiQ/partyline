<script lang="ts">
  /** The root line's one-click approvals banner: every pending person-decision
   * in the subtree, listed with Approve and Decline. Fed by the approvals
   * store; the wire's request events refresh it. */
  import { approvals } from "../state/approvals.svelte.js";

  function decide(item: (typeof approvals.items)[number], approve: boolean): void {
    void approvals.decide(item, approve);
  }
</script>

{#if approvals.items.length > 0}
  <div
    id="approvalsPending"
    class="flex flex-col gap-1 border-b px-3 py-2 font-mono text-[11px] leading-[1.35] text-copper border-[rgb(190_123_74/0.36)] bg-[rgb(190_123_74/0.08)]"
    role="region"
    aria-label="Approvals pending"
  >
    <strong class="font-semibold uppercase tracking-[0.08em]">
      approvals pending ({approvals.items.length})
    </strong>
    {#each approvals.items as item (item.conv_id + item.kind + item.request_id)}
      <div data-approval-row class="flex items-center gap-2">
        <span class="truncate">
          {item.kind} on «{item.line}» from @{item.requester} — {item.detail}
        </span>
        <button
          type="button"
          class="flex-none rounded-[3px] border border-emerald/55 bg-emerald/10 px-2 py-[2px] text-[10px] text-emerald hover:bg-emerald/25 disabled:opacity-40"
          disabled={approvals.deciding}
          onclick={() => {
            decide(item, true);
          }}
        >
          Approve
        </button>
        <button
          type="button"
          class="flex-none rounded-[3px] border border-red/55 bg-red/10 px-2 py-[2px] text-[10px] text-red hover:bg-red/25 disabled:opacity-40"
          disabled={approvals.deciding}
          onclick={() => {
            decide(item, false);
          }}
        >
          Decline
        </button>
      </div>
    {/each}
  </div>
{/if}
