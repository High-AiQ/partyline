<script lang="ts">
  /**
   * A process asked for extra write-set scope; a person decides it here.
   *
   * Approval records the grant and resumes every live process on this line
   * so the widened bind applies. The server owns the request's lifetime: if
   * another tab decides first, the banner and this dialog simply go away.
   */
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { writeSetApi } from "../../lib/write-set-api";
  import { writeSet } from "../../state/write-set.svelte.js";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  let busy = $state<"approve" | "decline" | null>(null);
  let error = $state("");

  $effect(() => {
    if (!writeSet.request) close();
  });

  async function decide(action: "approve" | "decline"): Promise<void> {
    const request = writeSet.request;
    const convId = room.conversation?.id;
    if (!request || !convId || busy) return;
    busy = action;
    error = "";
    try {
      if (action === "approve") {
        await writeSetApi.approve(convId, request.id);
      } else {
        await writeSetApi.decline(convId, request.id);
      }
      writeSet.request = null;
      close();
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "that did not work";
    } finally {
      busy = null;
    }
  }
</script>

<Modal title="grant write-set scope?" {close}>
  {#if writeSet.request}
    <p class="dialog-text">
      <strong>@{writeSet.request.requester}</strong> asks to widen this line's write set to:
      <code>{writeSet.request.path}</code>
    </p>
    <p class="dialog-text">
      Every live process on this line is detached and resumed with the new bind. Only grant paths you intend
      this line to write.
    </p>
    <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
    <div class="flex justify-end gap-2">
      <button type="button" disabled={busy !== null} onclick={() => void decide("decline")}
        >{busy === "decline" ? "declining…" : "decline"}</button
      >
      <button type="button" class="primary" disabled={busy !== null} onclick={() => void decide("approve")}
        >{busy === "approve" ? "granting…" : "approve grant"}</button
      >
    </div>
  {/if}
</Modal>
