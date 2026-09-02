<script lang="ts">
  /**
   * Record one immutable structured review decision on an agent presentation.
   *
   * Deliberately not built from `ConfirmForm`: there is no phrase to type, and
   * approve/reject are equal-weight choices that must never fire from one click
   * on the message itself.
   */
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import { visibleMessageBody } from "../../lib/files";
  import type { ReviewDecisionChoice } from "../../lib/review-decisions";
  import type { ChatMessage } from "../../lib/contracts";
  import { reviewDecisionStatus } from "../../state/review-decision-status.svelte.js";
  import { session } from "../../state/session.svelte.js";

  interface Props {
    message: ChatMessage;
    conversationId: string;
    close: () => void;
  }

  let { message, conversationId, close }: Props = $props();

  let busy = $state<ReviewDecisionChoice | null>(null);
  let error = $state("");
  let success = $state<ReviewDecisionChoice | null>(null);
  let successTimer: ReturnType<typeof setTimeout> | null = null;

  const preview = $derived(visibleMessageBody(message).trim().slice(0, 280));
  const truncated = $derived(visibleMessageBody(message).trim().length > 280);
  const locked = $derived(busy != null || success != null);

  function clearSuccessTimer(): void {
    if (successTimer !== null) {
      clearTimeout(successTimer);
      successTimer = null;
    }
  }

  $effect(() => () => {
    clearSuccessTimer();
  });

  function guardedClose(): void {
    if (busy != null) return;
    clearSuccessTimer();
    close();
  }

  async function decide(decision: ReviewDecisionChoice): Promise<void> {
    if (busy || success) return;
    const userId = session.user?.id;
    if (userId == null) {
      error = "sign in as a human to record a review decision";
      return;
    }
    busy = decision;
    error = "";
    try {
      await api.createReviewDecision(conversationId, {
        presentation_message_id: message.id,
        decision,
      });
      reviewDecisionStatus.record(conversationId, message.id, userId, decision);
      success = decision;
      clearSuccessTimer();
      successTimer = setTimeout(() => {
        successTimer = null;
        close();
      }, 900);
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not record decision";
      busy = null;
    }
  }
</script>

<Modal title="review agent presentation" close={guardedClose}>
  <p class="dialog-text">
    Record one immutable decision for <strong>@{message.sender}</strong> · message {message.id}. This cannot
    be changed later.
  </p>

  <div class="border-l-2 border-copper pl-[11px]">
    <div class="dialog-note">presentation excerpt</div>
    <p class="max-h-[30vh] overflow-y-auto text-[12px] whitespace-pre-wrap wrap-anywhere text-cream-dim">
      {preview}{#if truncated}…{/if}
    </p>
  </div>

  <div class="line-status" class:error={Boolean(error)} aria-live="polite">
    {#if success}
      {success === "approve" ? "approve recorded" : "reject recorded"}
    {:else}
      {error}
    {/if}
  </div>

  <div class="line-actions">
    <button type="button" class="min-h-11 min-w-11" disabled={locked} onclick={guardedClose}> cancel </button>
    <button
      type="button"
      class="danger min-h-11 min-w-[5.5rem]"
      disabled={locked}
      aria-label="Reject this agent presentation"
      onclick={() => {
        void decide("reject");
      }}
    >
      {busy === "reject" ? "recording…" : "reject"}
    </button>
    <button
      type="button"
      class="primary min-h-11 min-w-[5.5rem]"
      disabled={locked}
      aria-label="Approve this agent presentation"
      onclick={() => {
        void decide("approve");
      }}
    >
      {busy === "approve" ? "recording…" : "approve"}
    </button>
  </div>
</Modal>
