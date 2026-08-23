<script lang="ts">
  /** Human-owned switch for the line's one receipt-capable lead slot. */
  import { ApiError, api } from "../../lib/api";
  import type { Attachment } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    attachment: Attachment;
  }

  let { attachment }: Props = $props();
  let saving = $state(false);

  async function toggle(): Promise<void> {
    saving = true;
    try {
      room.upsertAttachment(await api.setAttachmentFollow(attachment.id, { follow: !attachment.follow }));
    } catch (error) {
      room.showNotice(error instanceof ApiError ? error.message : "could not change follow mode", "error");
    } finally {
      saving = false;
    }
  }
</script>

<button
  class="follow"
  class:active={attachment.follow}
  type="button"
  aria-label="{attachment.follow ? 'stop' : 'start'} hearing every message for {attachment.name}"
  aria-pressed={attachment.follow}
  title={attachment.follow
    ? "following every non-system message — click to stop"
    : "make this process the line's lead follower"}
  disabled={saving}
  onclick={toggle}
>
  {saving ? "saving…" : attachment.follow ? "◉ following" : "○ follow"}
</button>

<style>
  .follow {
    margin-top: 6px;
    font-size: 10px;
    padding: 2px 9px;
    color: var(--color-cream-faint);
    border-color: var(--color-line-hot);
  }
  .follow:hover,
  .follow.active {
    color: var(--color-copper-hot);
    border-color: rgb(217 142 74 / 0.55);
    background: rgb(217 142 74 / 0.08);
  }
</style>
