<script lang="ts">
  /**
   * Computers paired for screen sharing.
   *
   * This is the slot the screen-share server fills: pairing codes and the
   * device list replace this component's body. The route (`#/settings/computers`),
   * the nav entry and the search entry already exist, so that work touches only
   * this file. Until then nothing here is configurable, and it says so.
   */
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
</script>

<SettingsSection id="computers">
  <SettingRow
    id="setting-screen-devices"
    label="Screen sharing computers"
    description="Pair a computer to share its desktop into a line with the native screen helper (docs/screen-helper.md)."
    stacked
  >
    <div class="rounded border border-dashed border-line px-4 py-5 text-center">
      <p class="text-[12px] text-cream-dim">Pairing is not available on this server yet.</p>
      <p class="dialog-note mt-1">
        It arrives with the screen-share server; nothing here changes anything until then.
      </p>
    </div>
  </SettingRow>
</SettingsSection>
