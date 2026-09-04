<script lang="ts">
  /**
   * Forget a stopped jack. Its chat stays on the line; what goes is the card,
   * its token, and the ability to resume that CLI session from here — which is
   * why this asks, and why it is only offered once the process has stopped.
   */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { attachmentLifecycleApi } from "../../lib/attachment-lifecycle-api";
  import type { Attachment } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    attachment: Attachment;
    close: () => void;
  }

  let { attachment, close }: Props = $props();

  async function remove(): Promise<void> {
    await attachmentLifecycleApi.forget(attachment.id);
    if (room.conversation?.id === attachment.conv_id) room.removeAttachment(attachment.id);
    close();
  }
</script>

<Modal title="remove from roster · {attachment.name}" {close}>
  <p class="dialog-text">
    Removes this stopped jack from the line. Everything it said stays in the chat. Its session will no longer
    be tracked here, so <strong>↻ resume</strong> will not be offered for it again.
  </p>
  <ConfirmForm
    phrase={null}
    prompt=""
    label="remove {attachment.name}"
    busyLabel="removing…"
    onconfirm={remove}
    oncancel={close}
  />
</Modal>
