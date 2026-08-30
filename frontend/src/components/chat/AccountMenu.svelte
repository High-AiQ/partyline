<script lang="ts">
  /** Compact authenticated-user controls that stay reachable on mobile. */
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import ChangeHandleDialog from "../dialogs/ChangeHandleDialog.svelte";
</script>

<div class="account flex shrink-0 items-center gap-1.5">
  <button
    class="handle max-w-[150px] truncate px-[9px] py-0 text-copper-hot min-h-[34px]"
    type="button"
    title="change handle"
    aria-label="change handle, currently {session.handle}"
    onclick={() => dialogs.open(ChangeHandleDialog)}>@{session.handle}</button
  >
  <button
    class="logout px-[9px] py-0 text-cream-faint min-h-[34px] hover:border-red hover:bg-red"
    type="button"
    onclick={() => {
      session.logout();
    }}>logout</button
  >
</div>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written —
     at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH`. The
     tablet band lives here with it so the breakpoints read as one block. */
  @media (min-width: 900px) and (max-width: 1199px) {
    .account {
      gap: 4px;
    }
    .account button {
      padding: 0 7px;
    }
    .handle {
      max-width: 60px;
    }
    .logout {
      font-size: 9px;
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
      max-width: 92px;
    }
    .logout {
      font-size: 9px;
    }
  }
</style>
