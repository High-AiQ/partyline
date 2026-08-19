<script lang="ts">
  /** Compact authenticated-user controls that stay reachable on mobile. */
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import ChangeHandleDialog from "../dialogs/ChangeHandleDialog.svelte";
</script>

<div class="account">
  <button
    class="handle"
    type="button"
    title="change handle"
    aria-label="change handle, currently {session.handle}"
    onclick={() => dialogs.open(ChangeHandleDialog)}>@{session.handle}</button
  >
  <button
    class="logout"
    type="button"
    onclick={() => {
      session.logout();
    }}>logout</button
  >
</div>

<style>
  .account {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: none;
  }
  .account button {
    min-height: 34px;
    padding: 0 9px;
  }
  .handle {
    max-width: 150px;
    overflow: hidden;
    color: var(--color-copper-hot);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .logout {
    color: var(--color-cream-faint);
  }
  .logout:hover {
    border-color: var(--color-red);
    background: var(--color-red);
  }
  @media (max-width: 899px) {
    .account {
      gap: 4px;
    }
    .account button {
      min-height: 44px;
    }
    .handle {
      max-width: 92px;
    }
    .logout {
      padding: 0 7px;
      font-size: 9px;
    }
  }
</style>
