<script lang="ts">
  /** The line's standing brief. Agents receive it when they join, and hear
   *  about changes at their next wake — so it is worth a real editor. */
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  const MAX = 3000;
  const conversation: Conversation | null = room.conversation;

  let topic = $state(conversation?.topic ?? "");
  let saving = $state(false);
  let error = $state("");
  let field = $state<HTMLTextAreaElement | null>(null);

  $effect(() => {
    field?.focus();
  });

  async function save(): Promise<void> {
    if (!conversation) return;
    saving = true;
    error = "";
    try {
      room.conversation = await api.setTopic(conversation.id, topic);
      await room.loadConversations();
      close();
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not save topic";
      saving = false;
    }
  }
</script>

<Modal title="line topic · {conversation?.name ?? ''}" {close}>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
  <textarea
    class="min-h-[120px] resize-y rounded border border-line bg-ink px-[11px] py-[9px] text-[12px] text-cream outline-0 focus:border-copper"
    bind:this={field}
    bind:value={topic}
    maxlength={MAX}
    aria-label="line topic"
    placeholder={"what is this line about? project, culture, standing instructions —\nagents receive it in their join briefing, and hear about changes at their next wake"}
  ></textarea>
  <div class="flex items-baseline justify-between gap-2.5">
    <span class="text-[10px] text-cream-faint">{topic.length} / {MAX}</span>
    <button type="button" class="primary" disabled={saving} onclick={save}>
      {saving ? "saving…" : "save topic"}
    </button>
  </div>
</Modal>
