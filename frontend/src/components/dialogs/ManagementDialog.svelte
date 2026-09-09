<script lang="ts">
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import { hierarchyApi } from "../../lib/hierarchy-api";
  import type { Attachment, Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }
  let { conversation, close }: Props = $props();
  let attachments = $state<Attachment[]>([]);
  let parentId = $state("");
  let leadId = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let ready = $state(false);
  let error = $state("");
  let saved = $state("");

  $effect(() => {
    let cancelled = false;
    loading = true;
    void Promise.all([api.conversation(conversation.id), hierarchyApi.lead(conversation.id)])
      .then(([detail, lead]) => {
        if (cancelled) return;
        attachments = detail.attachments;
        parentId = detail.conversation.parent_id ?? "";
        leadId = lead.attachment_id ?? "";
        ready = true;
      })
      .catch((failure: unknown) => {
        if (!cancelled) error = failure instanceof ApiError ? failure.message : "could not load management";
      })
      .finally(() => {
        if (!cancelled) loading = false;
      });
    return () => {
      cancelled = true;
    };
  });

  async function save(kind: "parent" | "manager"): Promise<void> {
    saving = true;
    error = "";
    saved = "";
    try {
      if (kind === "parent") {
        const updated = await hierarchyApi.setParent(conversation.id, parentId || null);
        if (room.conversation?.id === updated.id) room.conversation = updated;
      } else {
        await hierarchyApi.setLead(conversation.id, leadId || null);
      }
      await room.loadConversations();
      saved = kind === "parent" ? "parent line updated" : "manager updated";
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not save management";
    } finally {
      saving = false;
    }
  }
</script>

<Modal title="management · {conversation.name}" {close}>
  <p class="dialog-note">A manager can create child lines, delegate work, and read their reports.</p>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error || saved}</div>
  {#if loading}
    <p class="py-5 text-cream-faint">loading management…</p>
  {:else if ready}
    <div class="line-form">
      <label for="parentLine">parent line</label>
      <select id="parentLine" bind:value={parentId} disabled={saving}>
        <option value="">none · independent line</option>
        {#each room.conversations.filter((line) => line.id !== conversation.id) as line (line.id)}
          <option value={line.id}>{line.name}</option>
        {/each}
      </select>
      <div class="line-actions">
        <button type="button" disabled={saving} onclick={() => save("parent")}>save parent</button>
      </div>
      <label for="lineManager">manager</label>
      <select id="lineManager" bind:value={leadId} disabled={saving}>
        <option value="">none · ordinary participants only</option>
        {#each attachments as attachment (attachment.id)}
          <option value={attachment.id}
            >@{attachment.name} · {attachment.adapter} · {attachment.status}</option
          >
        {/each}
      </select>
      <p class="dialog-note">
        Grant this role only to the process responsible for this line and its children.
      </p>
      <div class="line-actions">
        <button type="button" onclick={close}>close</button>
        <button class="primary" type="button" disabled={saving} onclick={() => save("manager")}
          >save manager</button
        >
      </div>
    </div>
  {:else}
    <button type="button" onclick={close}>close</button>
  {/if}
</Modal>
