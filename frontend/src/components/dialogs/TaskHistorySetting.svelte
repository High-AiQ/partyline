<script lang="ts">
  /** Auto-clean of finished task lines: saved the moment it changes, restored if the write fails. */
  import { onDestroy, onMount } from "svelte";
  import SettingRow from "../settings/SettingRow.svelte";
  import SaveIndicator from "../settings/SaveIndicator.svelte";
  import { orchestratorApi } from "../../lib/orchestrator-api";
  import { SaveTracker } from "../../lib/save-state";
  import type { SaveSnapshot } from "../../lib/save-state";

  let enabled = $state(false);
  let ready = $state(false);
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((next) => (save = next));
  onMount(() => {
    void orchestratorApi
      .history()
      .then((setting) => {
        enabled = setting.enabled;
        ready = true;
      })
      .catch(() => {
        save = { phase: "error", message: "could not load task history setting" };
      });
  });
  onDestroy(() => {
    tracker.dispose();
  });

  async function toggle(): Promise<void> {
    const previous = !enabled;
    const stored = await tracker.run(
      () => orchestratorApi.setHistory(enabled),
      "could not save task history setting",
    );
    enabled = stored ? stored.enabled : previous;
  }
</script>

<SettingRow
  id="setting-task-history"
  label="Auto-clean task history"
  control="autoCleanTaskHistory"
  description="Off by default. Archive approved or done tasks after merge, once no processes are live, and remove their worktrees. When off, task lines stay until a person archives them."
>
  <input
    id="autoCleanTaskHistory"
    class="switch"
    type="checkbox"
    role="switch"
    bind:checked={enabled}
    disabled={!ready || save.phase === "saving"}
    onchange={toggle}
  />
  {#snippet status()}<SaveIndicator state={save} />{/snippet}
</SettingRow>
