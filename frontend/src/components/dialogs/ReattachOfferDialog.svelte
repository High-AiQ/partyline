<script lang="ts">
  /**
   * The line came back, and the processes that were on it can come back too.
   *
   * Deliberately *not* built from `ConfirmForm`, which every other dialog in
   * this folder uses. That component exists to make you hesitate: a red button
   * and a phrase to type before something irreversible. Accepting a reattach
   * offer is the benign, expected path after a restart you scheduled yourself,
   * and putting friction on it would be an obstacle rather than a safeguard.
   * It shares `Modal` and the `.live-list` vocabulary so it still reads as
   * family; it just does not pretend to be dangerous.
   */
  import Modal from "../Modal.svelte";
  import { hue } from "../../lib/markdown";
  import { room } from "../../state/room.svelte.js";
  import type { ReattachOfferEvent } from "../../lib/contracts";

  interface Props {
    offer: ReattachOfferEvent;
  }

  let { offer }: Props = $props();

  /** How long to wait for the server's decision before admitting we did not
   *  hear one. Long enough to cover a slow round trip, short enough that
   *  nobody sits looking at a disabled dialog wondering. */
  const ACK_TIMEOUT_MS = 8000;

  let choosing = $state(false);
  let error = $state("");
  let ackTimer: ReturnType<typeof setTimeout> | null = null;

  // The dialog unmounts the instant a decision arrives, so this only ever runs
  // when one did not.
  $effect(() => () => {
    if (ackTimer) clearTimeout(ackTimer);
  });

  /**
   * The server broadcasts its decision, and *that* is what clears the offer —
   * in this tab and in every other one. Clearing it here would be a guess, and
   * a wrong one whenever the socket has gone since the dialog opened: the
   * offer would vanish from the screen while the plan sat un-consumed on disk.
   */
  function choose(action: "accept" | "cancel"): void {
    choosing = true;
    error = "";
    if (!room.chooseReattach(action)) {
      choosing = false;
      error = "the line is not reachable — try again when the wire is back";
      return;
    }
    // Sending is not hearing back. If the decision broadcast never arrives —
    // another tab already answered and this one missed it, or the socket went
    // between the send and the reply — the buttons would otherwise stay
    // disabled forever, leaving a dead dialog with no way out of it.
    if (ackTimer) clearTimeout(ackTimer);
    ackTimer = setTimeout(() => {
      ackTimer = null;
      choosing = false;
      error = "no answer from the server — this offer may already have been decided elsewhere";
    }, ACK_TIMEOUT_MS);
  }
</script>

<!-- `Modal`'s ✕ and backdrop route through `choose` rather than closing
     directly. Dismissing this dialog *is* declining the offer, and declining
     is a message to the server: if it cannot be sent, the dialog has to say so
     instead of vanishing and leaving a plan sitting un-consumed on disk. -->
<Modal
  title="processes were on this line"
  close={() => {
    choose("cancel");
  }}
>
  <p class="dialog-text">
    partyline restarted. These processes can be brought back one at a time, each given the briefing below
    before the next one starts.
  </p>

  <div class="live-list">
    {#each offer.attachments as attachment (attachment.id)}
      <!-- `.live-item` is shared with the delete-line and stop-server dialogs,
           where the list means "these will be stopped" and the red wash is a
           warning. Here the same list means the opposite — these are coming
           back — so the shape is kept and the alarm is taken out of it: the
           utilities below sit in a later layer than the shared component, so
           they win at equal specificity. -->
      <div class="live-item border-line bg-ink-3">
        <!-- nothing is running yet — a lit LED would claim something untrue -->
        <span class="led"></span>
        <span style:color="hsl({hue(attachment.name.toLowerCase())} 55% 68%)">@{attachment.name}</span>
        <span class="on">{attachment.adapter}</span>
      </div>
    {/each}
  </div>

  {#if offer.debrief}
    <div class="border-l-2 border-copper pl-[11px]">
      <div class="dialog-note">each one wakes with this</div>
      <p class="max-h-[30vh] overflow-y-auto text-[12px] whitespace-pre-wrap wrap-anywhere text-cream-dim">
        {offer.debrief}
      </p>
    </div>
  {/if}

  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>

  <div class="line-actions">
    <button
      type="button"
      disabled={choosing}
      onclick={() => {
        choose("cancel");
      }}>not now</button
    >
    <button
      class="primary"
      type="button"
      disabled={choosing}
      onclick={() => {
        choose("accept");
      }}>{choosing ? "bringing them back…" : "reattach"}</button
    >
  </div>
</Modal>
