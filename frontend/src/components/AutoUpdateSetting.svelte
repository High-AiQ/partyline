<script lang="ts">
  import { screenApi, type ScreenDevice } from "../lib/screen-api";
  interface Props {
    device: ScreenDevice;
  }
  let { device }: Props = $props();
  let saving = $state(false);
  let error = $state("");
  async function change(event: Event): Promise<void> {
    if (!(event.target instanceof HTMLInputElement)) return;
    const enabled = event.target.checked;
    saving = true;
    error = "";
    try {
      await screenApi.autoUpdate(device.id, enabled);
    } catch {
      error = "Could not save automatic updates";
      event.target.checked = device.auto_update ?? false;
    } finally {
      saving = false;
    }
  }
</script>

<label class="flex items-center gap-2 text-sm">
  <input
    type="checkbox"
    checked={device.auto_update ?? false}
    disabled={saving}
    onchange={(event) => void change(event)}
  />
  Install updates automatically
</label>
{#if device.updating}<p class="text-sm" role="status">Updating helper; window access paused</p>{/if}
{#if error}<p role="alert">{error}</p>{/if}
