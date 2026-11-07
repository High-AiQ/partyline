<script lang="ts">
  /**
   * Computers paired for screen sharing.
   *
   * Pairing codes are minted per line in the chat's "Computers / Share screen"
   * dialog; this section shows the same helper steps with a placeholder code.
   */
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import PairingSteps from "../../PairingSteps.svelte";
</script>

<SettingsSection id="computers">
  <SettingRow
    id="setting-screen-devices"
    label="Screen sharing computers"
    description="Pair a computer to share its desktop into a line with the native screen helper (docs/screen-helper.md). Open a line and choose “Computers / Share screen” to get a pairing code (valid for 5 minutes)."
    stacked
  >
    <PairingSteps origin={window.location.origin} code="YOUR-CODE" />
  </SettingRow>
</SettingsSection>
