<script lang="ts">
  /**
   * Stop partyline itself.
   *
   * Deliberately built from the same pieces as the delete-line dialog: same
   * `Modal`, same `ConfirmForm`, same `.live-list` vocabulary. A one-off
   * overlay here would be a second thing to keep in step with the first.
   */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api";
  import type { RunningProcess } from "../../lib/contracts";
  import { wire } from "../../state/wire.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  let loading = $state(true);
  let running = $state<RunningProcess[]>([]);

  $effect(() => {
    // The list is a courtesy — the warning below stands either way, so a
    // failure to fetch it must not block the dialog.
    api
      .running()
      .then((processes) => {
        running = processes;
      })
      .catch(() => {
        running = [];
      })
      .finally(() => {
        loading = false;
      });
  });

  async function stop(): Promise<void> {
    await api.shutdown();
    close();
    // The server broadcasts `shutdown` before it goes, but say it here too:
    // this tab asked for it, so it should not wait on a race to find out.
    wire.reportStopped();
  }
</script>

<Modal title="stop partyline" {close}>
  {#if loading}
    <p class="dialog-text">Checking what is running…</p>
  {:else}
    <p class="dialog-text">
      This stops the partyline server itself — every line, and every process on every line. Nothing here can
      start it again: you will need a terminal.
    </p>

    <div class="live-list">
      {#if running.length}
        <div class="dialog-note">these processes will be stopped</div>
        <!-- Keyed by index: a handle is unique per line but not across lines,
             so name+line can still collide, and this list is a static snapshot
             that is never reordered. -->
        {#each running as process, index (index)}
          <div class="live-item">
            <span class="led running"></span>
            <span>@{process.name}</span>
            <span class="on">on {process.conversation}</span>
          </div>
        {/each}
      {:else}
        <div class="dialog-note">no processes are attached</div>
      {/if}
    </div>

    <ConfirmForm
      phrase={running.length ? "stop" : null}
      prompt="type stop to confirm"
      label="stop partyline"
      busyLabel="stopping…"
      onconfirm={stop}
      oncancel={close}
    />
  {/if}
</Modal>
