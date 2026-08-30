<script lang="ts">
  /**
   * Stop partyline itself, and optionally arrange for this line's processes to
   * be offered back when it returns.
   *
   * Deliberately built from the same pieces as the delete-line dialog: same
   * `Modal`, same `ConfirmForm`, same `.live-list` vocabulary. A one-off
   * overlay here would be a second thing to keep in step with the first.
   */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api";
  import type { RunningProcess } from "../../lib/contracts";
  import { canResume, isLive, latestJacks } from "../../lib/attachments";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import { wire } from "../../state/wire.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  const DEBRIEF_MAX = 10_000;

  let loading = $state(true);
  let running = $state<RunningProcess[]>([]);
  let planReattach = $state(false);
  let debrief = $state("");

  /**
   * The processes a plan could actually cover.
   *
   * A plan is scoped to the requesting line, and the server takes only live
   * attachments whose adapter can reopen a session. Asking for one when none
   * qualify is a 409 that aborts the whole shutdown — so the offer is not made
   * unless it can be honoured. `raw` is the common case here: it has no
   * session to resume, so silence from it is not evidence that anything is
   * ready, and it is deliberately not restartable.
   */
  const resumable = $derived(
    latestJacks(room.attachments).filter(
      (attachment) => isLive(attachment) && canResume(session.adapters, attachment.adapter),
    ),
  );
  const canPlan = $derived(room.conversation !== null && resumable.length > 0);

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
    const conversation = room.conversation;
    await api.shutdown(
      planReattach && conversation
        ? { conversation_id: conversation.id, debrief: debrief.trim() }
        : undefined,
    );
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

    {#if canPlan}
      <div class="flex flex-col gap-[7px] border-t border-dashed border-line pt-2.5">
        <label class="flex cursor-pointer items-start gap-2 text-[11.5px] text-cream-dim">
          <!-- A checkbox is a real hit target, not a decoration beside the label. -->
          <input
            type="checkbox"
            class="mt-[1px] h-[15px] w-[15px] flex-none accent-copper"
            bind:checked={planReattach}
          />
          <span>
            offer to bring back {resumable.length}
            {resumable.length === 1 ? "process" : "processes"} on
            <b class="font-semibold text-copper-hot">{room.conversation?.name ?? "this line"}</b> when partyline
            returns
          </span>
        </label>

        {#if planReattach}
          <label class="text-[10px] tracking-[0.05em] text-cream-faint" for="restartDebrief">
            what they should be told on the way back in
          </label>
          <textarea
            id="restartDebrief"
            class="min-h-[84px] resize-y rounded border border-line bg-ink px-[11px] py-[9px] text-[12px] text-cream outline-0 focus:border-copper"
            bind:value={debrief}
            maxlength={DEBRIEF_MAX}
            placeholder={"restarting to pick up the new build — pull, re-read your slice, and post status.\nthey come back one at a time, each fully ready before the next starts"}
          ></textarea>
          <div class="dialog-note">
            only this line, and only processes whose adapter can reopen its session
          </div>
        {/if}
      </div>
    {/if}

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
