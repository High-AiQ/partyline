<script lang="ts">
  import { ApiError } from "../../lib/api";
  import { orchestratorApi } from "../../lib/orchestrator-api";
  import { room } from "../../state/room.svelte";
  const line = $derived(
    room.conversations.find((candidate) => candidate.id === room.conversation?.id) ?? room.conversation,
  );
  let restarting = $state(false);
  let error = $state("");
  async function restartReviewer(): Promise<void> {
    if (!line) return;
    restarting = true;
    error = "";
    try {
      await orchestratorApi.restartReviewer(line.id);
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not restart the reviewer";
    } finally {
      restarting = false;
    }
  }
</script>

{#if line?.task_status}
  <div
    id="task-header"
    class="border-b border-line bg-ink-2 px-4 py-2 text-[11px] leading-relaxed text-cream-dim"
  >
    task of «{line.task_root_name ?? "root"}» · implementer: {line.task_implementer_name ?? "pending"} · reviewer:
    {line.task_reviewer_name ?? "pending"}
    {#if (line.task_repositories?.length ?? 0) > 1}
      <div id="task-repositories">reviewing {line.task_repositories?.join(" · ")}</div>
    {/if}
    {#if line.task_status === "in_review"}
      <button
        id="restart-reviewer"
        type="button"
        class="ml-2 rounded border border-line px-2 py-0.5 text-cream hover:bg-ink-3"
        disabled={restarting}
        onclick={restartReviewer}>restart reviewer</button
      >
    {/if}
    {#if error}<span role="alert" class="ml-2 text-red-400">{error}</span>{/if}
  </div>
{/if}
