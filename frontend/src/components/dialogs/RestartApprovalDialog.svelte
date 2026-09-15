<script lang="ts">
  /**
   * A captain asked for a service restart; a person decides it here.
   *
   * Approval restarts partyline itself and resumes every live process with
   * its context, so the whole fleet is listed, not just this line. The
   * server owns the request's lifetime: if another tab decides first, the
   * banner and this dialog simply go away.
   */
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import { restartApi } from "../../lib/restart-api";
  import { restart } from "../../state/restart.svelte.js";
  import type { RunningProcess } from "../../lib/contracts";
  import { wire } from "../../state/wire.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  let loading = $state(true);
  let running = $state<RunningProcess[]>([]);
  let busy = $state<"approve" | "decline" | null>(null);
  let error = $state("");

  $effect(() => {
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

  $effect(() => {
    if (!restart.request) close();
  });

  async function decide(action: "approve" | "decline"): Promise<void> {
    const request = restart.request;
    if (!request || busy) return;
    busy = action;
    error = "";
    try {
      if (action === "approve") {
        await restartApi.approve(request.id);
        restart.request = null;
        close();
        wire.reportStopped();
      } else {
        await restartApi.decline(request.id);
        restart.request = null;
        close();
      }
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "that did not work";
    } finally {
      busy = null;
    }
  }
</script>

<Modal title="restart partyline?" {close}>
  {#if restart.request}
    <p class="dialog-text">
      <strong>@{restart.request.requester}</strong> asks to restart the service:
      {restart.request.reason}
    </p>
    <p class="dialog-text">
      Every live process is stopped and resumed with its context when partyline is back. Anyone mid-turn is
      told to continue where it left off.
    </p>
    <div class="live-list">
      {#if loading}
        <div class="dialog-note">loading live processes…</div>
      {:else if running.length}
        <div class="dialog-note">{running.length} live process{running.length === 1 ? "" : "es"}</div>
        {#each running as process (process.name + process.conversation)}
          <div class="live-item">
            <span class="led running"></span><span>@{process.name} · {process.conversation}</span>
          </div>
        {/each}
      {:else}
        <div class="dialog-note">no live processes — the restart only brings up the new code</div>
      {/if}
    </div>
    <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
    <div class="flex justify-end gap-2">
      <button type="button" disabled={busy !== null} onclick={() => void decide("decline")}
        >{busy === "decline" ? "declining…" : "decline"}</button
      >
      <button type="button" class="danger" disabled={busy !== null} onclick={() => void decide("approve")}
        >{busy === "approve" ? "restarting…" : "approve restart"}</button
      >
    </div>
  {/if}
</Modal>
