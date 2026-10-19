<script lang="ts">
  import { room } from "../../state/room.svelte";
  const line = $derived(
    room.conversations.find((candidate) => candidate.id === room.conversation?.id) ?? room.conversation,
  );
</script>

{#if line?.task_status}
  <div
    id="task-header"
    class="border-b border-line bg-ink-2 px-4 py-2 text-[11px] leading-relaxed text-cream-dim"
  >
    task of «{line.task_root_name ?? "root"}» · implementer: {line.task_implementer_name ?? "pending"} · reviewer:
    {line.task_reviewer_name ?? "pending"}
  </div>
{/if}
