<script lang="ts">
  /** Delete an archived line for good. The one action here with no way back. */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }

  let { conversation, close }: Props = $props();

  async function purge(): Promise<void> {
    await api.purgeConversation(conversation.id);
    close();
    await room.loadArchived();
  }
</script>

<Modal title="delete forever · {conversation.name}" {close}>
  <p class="dialog-text">
    This permanently deletes the line’s messages, attachments, and history. It cannot be undone.
  </p>
  <ConfirmForm
    phrase={conversation.name}
    prompt="type the line name to confirm"
    label="delete forever"
    busyLabel="deleting…"
    onconfirm={purge}
    oncancel={close}
  />
</Modal>
