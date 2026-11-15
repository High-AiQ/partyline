<script lang="ts">
  /**
   * Ask before a favorite is unstarred.
   *
   * Starring is one click; losing a favorite to a stray tap is what this guards.
   * Same `Modal` and `.line-actions` as the other dialogs, but nothing to type:
   * the action is trivially undone, so a confirm button is enough. Cancel takes
   * focus, so Enter on arrival can never remove anything. Esc is the dialog
   * stack's, a backdrop click is `Modal`'s; neither touches the star.
   */
  import Modal from "../Modal.svelte";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";
  import { toggleConversationStar } from "../../state/conversation-star";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }

  let { conversation, close }: Props = $props();

  let cancelButton = $state<HTMLButtonElement>();
  let busy = $state(false);

  $effect(() => {
    cancelButton?.focus();
  });

  async function remove(): Promise<void> {
    busy = true;
    // Another tab may have unstarred it while this was open; a toggle would
    // star it back. A failure is reported by the toggle as the usual notice.
    if (room.conversations.find((line) => line.id === conversation.id)?.starred) {
      await toggleConversationStar(room, conversation.id);
    }
    close();
  }
</script>

<Modal title="Remove from favorites?" {close}>
  <p class="dialog-text">
    <b class="font-semibold text-copper-hot">{conversation.name}</b> will leave Starred. You can star it again any
    time.
  </p>
  <div class="line-actions">
    <button type="button" bind:this={cancelButton} onclick={close}>Cancel</button>
    <button class="danger" type="button" disabled={busy} onclick={remove}>Remove</button>
  </div>
</Modal>
