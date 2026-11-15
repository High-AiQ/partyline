<script lang="ts">
  import { onDestroy } from "svelte";
  import { SaveTracker, type SaveSnapshot } from "../lib/save-state";
  import { screenApi, type ScreenDevice } from "../lib/screen-api";
  import { room } from "../state/room.svelte.js";
  import LineMultiSelect, { type LineOption } from "./LineMultiSelect.svelte";
  import SaveIndicator from "./settings/SaveIndicator.svelte";

  let { device }: { device: ScreenDevice } = $props();
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((state) => (save = state));
  onDestroy(() => {
    tracker.dispose();
  });
  let options = $state<LineOption[]>([]);
  let error = $state("");
  const selected = $derived(
    device.window_access_lines ?? (device.window_access_line ? [device.window_access_line] : []),
  );
  $effect(() => {
    // Refresh on pushed line/process and computer changes, never on a timer.
    void room.conversations;
    void selected;
    const id = device.id;
    let cancelled = false;
    screenApi
      .windowLineOptions(id)
      .then((result) => {
        if (!cancelled) {
          options = result.lines;
          error = "";
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) error = cause instanceof Error ? cause.message : "Could not load lines";
      });
    return () => {
      cancelled = true;
    };
  });
  async function authorize(lines: string[]): Promise<void> {
    await tracker.run(() => screenApi.authorizeWindowLines(device.id, lines));
  }
</script>

<div class="my-2 flex min-w-0 flex-col gap-1">
  <LineMultiSelect
    label={`Window access for ${device.name}`}
    {options}
    {selected}
    disabled={save.phase === "saving"}
    onchange={(lines: string[]) => void authorize(lines)}
  />
  {#if error}<p role="alert">{error}</p>{/if}
  <SaveIndicator state={save} />
</div>
