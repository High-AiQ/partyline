<script lang="ts">
  import { onDestroy } from "svelte";
  import { SaveTracker, type SaveSnapshot } from "../lib/save-state";
  import { screenApi, type ScreenDevice } from "../lib/screen-api";
  import { room } from "../state/room.svelte.js";
  import SaveIndicator from "./settings/SaveIndicator.svelte";

  let { device }: { device: ScreenDevice } = $props();
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((state) => (save = state));
  onDestroy(() => {
    tracker.dispose();
  });
  async function authorize(event: Event): Promise<void> {
    if (!(event.currentTarget instanceof HTMLSelectElement)) return;
    const select = event.currentTarget;
    const result = await tracker.run(() => screenApi.authorizeWindowLine(device.id, select.value || null));
    if (!result) select.value = device.window_access_line ?? "";
  }
</script>

<div class="my-2 flex flex-col gap-1">
  <label>
    Window access for {device.name}
    <select value={device.window_access_line ?? ""} disabled={save.phase === "saving"} onchange={authorize}>
      <option value="">No lines</option>
      {#each room.conversations.filter((line) => !line.archived_at) as line (line.id)}
        <option value={line.id}>{line.name} and its sublines</option>
      {/each}
    </select>
  </label>
  <small
    >Allow agents on this line and its sublines to see and use windows when the helper's window access toggle
    is on.</small
  >
  <SaveIndicator state={save} />
</div>
