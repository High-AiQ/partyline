<script lang="ts">
  /**
   * Keeps the settings modal in step with the URL: a `#/settings/<tab>` route
   * opens it (deep link, Back, Forward), leaving the route closes it, and
   * closing it any other way leaves the route (the modal reports that itself).
   */
  import { untrack } from "svelte";
  import SettingsDialog from "../dialogs/SettingsDialog.svelte";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { settingsNav } from "../../state/settings-nav.svelte.js";

  let closeDialog: (() => void) | null = null;

  $effect(() => {
    const open = settingsNav.section !== null;
    untrack(() => {
      if (open && !closeDialog) {
        closeDialog = dialogs.open(SettingsDialog, {
          ondismiss: () => {
            closeDialog = null;
          },
        });
      } else if (!open && closeDialog) {
        const close = closeDialog;
        closeDialog = null;
        close();
      }
    });
  });
</script>

<svelte:window
  onhashchange={() => {
    settingsNav.sync();
  }}
/>
