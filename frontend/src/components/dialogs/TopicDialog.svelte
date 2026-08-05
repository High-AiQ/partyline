<script>
  /** The line's standing brief. Agents receive it when they join, and hear
   *  about changes at their next wake — so it is worth a real editor. */
  import Modal from "../Modal.svelte";
  import { api } from "../../lib/api.js";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";

  let { close } = $props();

  const MAX = 3000;
  const conversation = room.conversation;

  let topic = $state(conversation?.topic ?? "");
  let saving = $state(false);
  let error = $state("");
  let field = $state(null);

  $effect(() => {
    field?.focus();
  });

  async function save() {
    saving = true;
    error = "";
    try {
      room.conversation = await api.setTopic(conversation.id, topic, session.handle);
      await room.loadConversations();
      close();
    } catch (failure) {
      error = failure.message;
      saving = false;
    }
  }
</script>

<Modal title="line topic · {conversation?.name ?? ''}" {close}>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
  <textarea
    class="topicBox"
    bind:this={field}
    bind:value={topic}
    maxlength={MAX}
    aria-label="line topic"
    placeholder={"what is this line about? project, culture, standing instructions —\nagents receive it in their join briefing, and hear about changes at their next wake"}
  ></textarea>
  <div class="topicRow">
    <span class="count">{topic.length} / {MAX}</span>
    <button type="button" class="primary" disabled={saving} onclick={save}>
      {saving ? "saving…" : "save topic"}
    </button>
  </div>
</Modal>

<style>
  .topicBox {
    background: var(--color-ink);
    border: 1px solid var(--color-line);
    border-radius: 4px;
    color: var(--color-cream);
    padding: 9px 11px;
    font: inherit;
    font-size: 12px;
    min-height: 120px;
    resize: vertical;
    outline: 0;
  }
  .topicBox:focus {
    border-color: var(--color-copper);
  }
  .topicRow {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
  }
  .count {
    color: var(--color-cream-faint);
    font-size: 10px;
  }
</style>
