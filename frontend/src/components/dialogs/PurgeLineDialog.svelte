<script>
  /** Delete an archived line for good. The one action here with no way back. */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { api } from "../../lib/api.js";
  import { room } from "../../state/room.svelte.js";

  let { conversation, close } = $props();

  async function purge() {
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
