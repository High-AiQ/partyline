<script lang="ts">
  import type { Conversation } from "../../lib/contracts";
  interface Props {
    status: Conversation["task_status"];
    round: number | null | undefined;
  }
  let { status, round }: Props = $props();
</script>

{#if status}
  <span
    class="task-status inline-flex w-fit max-w-full rounded border px-1.5 py-0.5 text-[9px] leading-tight whitespace-nowrap {status ===
    'in_review'
      ? 'border-copper/30 bg-copper/10 text-copper'
      : status === 'approved' || status === 'done'
        ? 'border-green/30 text-green'
        : status === 'blocked'
          ? 'border-red/30 text-red'
          : 'border-line text-cream-faint'}"
  >
    {status === "in_review" ? `in review · round ${String(round ?? 0)}` : status}
  </span>
{/if}
