<script>
  import Modal from "../Modal.svelte";
  import { api } from "../../lib/api.js";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";

  let { conversation, close } = $props();

  /* svelte-ignore state_referenced_locally */
  let name = $state(conversation.name);
  let saving = $state(false);
  let error = $state("");
  let field = $state(null);

  $effect(() => {
    field?.focus();
    field?.select();
  });

  async function save(event) {
    event.preventDefault();
    const next = name.trim();
    if (!next) return field?.focus();

    saving = true;
    error = "";
    try {
      const renamed = await api.renameConversation(conversation.id, next, session.handle);
      // The socket broadcasts this to everyone else; the tab that asked should
      // not have to wait on its own round trip to see it.
      if (room.conversation?.id === renamed.id) room.conversation = renamed;
      await room.loadConversations();
      close();
    } catch (failure) {
      error = failure.message;
      saving = false;
    }
  }
</script>

<Modal title="rename line · {conversation.name}" {close}>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
  <form class="line-form" onsubmit={save}>
    <label for="renameLine">new line name</label>
    <input id="renameLine" bind:this={field} bind:value={name} maxlength="120" autocomplete="off" />
    <div class="line-actions">
      <button type="button" onclick={close}>cancel</button>
      <button class="primary" type="submit" disabled={saving}>{saving ? "saving…" : "save name"}</button>
    </div>
  </form>
</Modal>
