<script lang="ts">
  /** Computers paired with this account for screen sharing. */
  import { screenApi } from "../../../lib/screen-api";
  import { screenStatus } from "../../../state/screen-status.svelte.js";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import PairingSteps from "../../PairingSteps.svelte";
  const devices = $derived(screenStatus.devices);
  let code = $state("");
  let error = $state("");
  async function pair(): Promise<void> {
    try {
      code = (await screenApi.pair()).code;
    } catch {
      error = "Could not create pairing code";
    }
  }
  async function revoke(id: string): Promise<void> {
    try {
      await screenApi.revoke(id);
    } catch {
      error = "Could not revoke computer";
    }
  }
</script>

<SettingsSection id="computers">
  <SettingRow
    id="setting-screen-devices"
    label="Screen sharing computers"
    description="Pair computers with your Partyline account to share them from any line."
    stacked
  >
    <button type="button" onclick={() => void pair()}>Pair this computer with Partyline</button>
    {#if code}<p>Code: <strong>{code}</strong> (expires in 5 minutes)</p>{/if}
    {#each devices as device (device.id)}
      <p>
        {device.name} ({device.online ? "online" : "offline"})
        <button type="button" onclick={() => void revoke(device.id)}>Revoke</button>
      </p>
    {/each}
    {#if error}<p role="alert">{error}</p>{/if}
    <PairingSteps origin={window.location.origin} code={code || "YOUR-CODE"} />
  </SettingRow>
</SettingsSection>
