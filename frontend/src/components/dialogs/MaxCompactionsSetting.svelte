<script lang="ts">
  /** The compaction limit: saved when the number changes, restored if the write fails. */
  import { onDestroy, onMount } from "svelte";
  import SettingRow from "../settings/SettingRow.svelte";
  import SaveIndicator from "../settings/SaveIndicator.svelte";
  import { getMaxCompactions, setMaxCompactions } from "../../lib/settings-api";
  import { SaveTracker } from "../../lib/save-state";
  import type { SaveSnapshot } from "../../lib/save-state";

  let value = $state<number | null>(2);
  let stored = 2;
  let ready = $state(false);
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((next) => (save = next));
  onMount(() => {
    void getMaxCompactions()
      .then((setting) => {
        stored = setting.value;
        value = stored;
        ready = true;
      })
      .catch(() => {
        save = { phase: "error", message: "could not load the compaction limit" };
      });
  });
  onDestroy(() => {
    tracker.dispose();
  });

  async function commit(): Promise<void> {
    const wanted = value;
    if (wanted === null || !Number.isInteger(wanted) || wanted < 0 || wanted > 20) {
      save = { phase: "error", message: "enter a whole number from 0 to 20" };
      value = stored;
      return;
    }
    if (wanted === stored) return;
    const saved = await tracker.run(() => setMaxCompactions(wanted), "could not save the compaction limit");
    stored = saved ? saved.value : stored;
    value = stored;
  }
</script>

<SettingRow
  id="setting-max-compactions"
  label="Maximum compactions per process"
  control="maxCompactions"
  description="After this many compactions a process is asked for a hand-off note at the end of its turn and replaced by a fresh instance of itself (same handle, line and role), briefed from that note. 0 turns it off; a preset can override it."
>
  <input
    id="maxCompactions"
    type="number"
    min="0"
    max="20"
    step="1"
    bind:value
    disabled={!ready || save.phase === "saving"}
    onchange={commit}
  />
  {#snippet status()}<SaveIndicator state={save} />{/snippet}
</SettingRow>
