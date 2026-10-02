<script lang="ts">
  /** Compact authenticated-user controls that stay reachable on mobile. */
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import { tooltip } from "../../lib/tooltip";
  import ChangeHandleDialog from "../dialogs/ChangeHandleDialog.svelte";
  import SettingsDialog from "../dialogs/SettingsDialog.svelte";
</script>

<div class="account flex shrink-0 items-center gap-1.5">
  <button
    class="settings topbar-action px-[9px] py-0 min-h-[34px]"
    type="button"
    aria-label="settings"
    use:tooltip={{ label: "settings" }}
    onclick={() => dialogs.open(SettingsDialog)}
    ><span class="button-label">settings</span><svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      class="settings-icon"
      ><circle cx="12" cy="12" r="3" /><path
        d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a7.8 7.8 0 0 1-1.5.9l-.3 1.8h-2.8l-.3-1.8a7.8 7.8 0 0 1-1.5-.9l-1.7.7-1.4-2.4 1.4-1.1a7 7 0 0 1 0-1.8l-1.4-1.1 1.4-2.4 1.7.7a7.8 7.8 0 0 1 1.5-.9l.3-1.8h2.8l.3 1.8a7.8 7.8 0 0 1 1.5.9l1.7-.7 1.4 2.4-1.4 1.1a7 7 0 0 1 0 1.8Z"
      /></svg
    ></button
  >
  <button
    class="handle topbar-action topbar-action-accented max-w-[150px] truncate px-[9px] py-0 min-h-[34px]"
    type="button"
    use:tooltip={{ label: "change handle" }}
    aria-label="change handle, currently {session.handle}"
    onclick={() => dialogs.open(ChangeHandleDialog)}>@{session.handle}</button
  >
  <button
    class="logout topbar-action topbar-action-danger px-[9px] py-0 min-h-[34px]"
    type="button"
    aria-label="logout"
    onclick={() => {
      session.logout();
    }}
    ><span class="button-label">logout</span><svg aria-hidden="true" viewBox="0 0 24 24" class="logout-icon"
      ><path d="M10 17l5-5-5-5M15 12H3m9-8h7a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-7" /></svg
    ></button
  >
</div>

<style>
  .settings-icon,
  .logout-icon {
    display: none;
  }

  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written —
     at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH`. The
     tablet band lives here with it so the breakpoints read as one block. */
  @media (min-width: 900px) and (max-width: 1200px) {
    .account {
      gap: 4px;
    }
    .settings,
    .logout {
      display: flex;
      align-items: center;
      width: 30px;
      min-width: 30px;
      justify-content: center;
      padding: 0;
      font-size: 0;
    }
    .settings-icon,
    .logout-icon {
      display: block;
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.7;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .button-label {
      display: none;
    }
    .handle {
      max-width: 40px;
      padding: 0 5px;
      font-size: 10px;
    }
  }
  @media (max-width: 899px) {
    .account {
      gap: 4px;
    }
    .account button {
      min-height: 44px;
    }
    .handle {
      max-width: 48px;
      padding: 0 4px;
      font-size: 10px;
    }
    .settings,
    .logout {
      display: flex;
      align-items: center;
      width: 44px;
      min-width: 44px;
      justify-content: center;
      padding: 0;
      font-size: 0;
    }
    .settings-icon,
    .logout-icon {
      display: block;
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.7;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .button-label {
      display: none;
    }
  }
</style>
