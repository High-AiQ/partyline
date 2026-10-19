<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../../lib/api";
  import { orchestratorApi } from "../../lib/orchestrator-api";
  let enabled = $state(false);
  let ready = $state(false);
  let saving = $state(false);
  let error = $state("");
  onMount(() => {
    void orchestratorApi
      .history()
      .then((setting) => {
        enabled = setting.enabled;
        ready = true;
      })
      .catch(() => {
        error = "could not load task history setting";
      });
  });
  async function save(): Promise<void> {
    const previous = !enabled;
    saving = true;
    error = "";
    try {
      enabled = (await orchestratorApi.setHistory(enabled)).enabled;
    } catch (failure: unknown) {
      enabled = previous;
      error = failure instanceof ApiError ? failure.message : "could not save task history setting";
    } finally {
      saving = false;
    }
  }
</script>

<section class="mb-5 border-b border-line pb-4" aria-label="task history">
  <h2 class="mb-2 text-[12px] text-cream">task history</h2>
  <label class="flex items-center gap-2 text-[12px] text-cream-dim" for="autoCleanTaskHistory">
    <input
      id="autoCleanTaskHistory"
      type="checkbox"
      bind:checked={enabled}
      disabled={!ready || saving}
      onchange={save}
    />
    auto-clean task and review history
  </label>
  <p class="dialog-note mt-2">
    Off by default. Archive approved or done tasks after merge, once no processes are live, and remove their
    worktrees.
  </p>
  <p class="dialog-note">When off, task lines stay until a person archives them.</p>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">
    {error || (saving ? "saving…" : "")}
  </div>
</section>
