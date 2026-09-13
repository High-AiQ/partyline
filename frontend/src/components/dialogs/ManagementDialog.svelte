<script lang="ts">
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import { hierarchyApi } from "../../lib/hierarchy-api";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";
  import { isLive } from "../../lib/attachments";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }
  let { conversation, close }: Props = $props();
  let parentId = $state("");
  let captainId = $state("");
  let appointing = $state(false);
  let loading = $state(true);
  let saving = $state(false);
  let ready = $state(false);
  let error = $state("");
  let saved = $state("");

  /** A line's parent can be set once or cleared, never re-pointed: the
   *  parent is chosen when the line is created or adopted, and changing it
   *  later is not a supported operation. */
  const parentName = $derived(
    room.conversations.find((line) => line.id === parentId)?.name ?? "the parent line",
  );

  $effect(() => {
    let cancelled = false;
    loading = true;
    void api
      .conversation(conversation.id)
      .then((detail) => {
        if (cancelled) return;
        parentId = detail.conversation.parent_id ?? "";
        return hierarchyApi.lead(conversation.id);
      })
      .then((lead) => {
        if (cancelled) return;
        captainId = lead?.attachment_id ?? "";
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

  /** A person appoints the captain here; the server rings it at once with the captain
   *  pack, and from then on only that captain (or a person) can appoint another. */
  async function appointCaptain(): Promise<void> {
    appointing = true;
    error = "";
    saved = "";
    try {
      const lead = await hierarchyApi.appoint(conversation.id, captainId || null);
      captainId = lead.attachment_id ?? "";
      room.setCaptain(conversation.id, lead.attachment_id);
      saved = captainId ? "captain appointed · it has been rung with the captain pack" : "captain cleared";
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not appoint the captain";
    } finally {
      appointing = false;
    }
  }

  async function saveParent(value: string | null): Promise<void> {
    saving = true;
    error = "";
    saved = "";
    try {
      const updated = await hierarchyApi.setParent(conversation.id, value);
      if (room.conversation?.id === updated.id) room.conversation = updated;
      await room.loadConversations();
      saved = value ? "parent line set" : "parent line cleared";
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not save management";
    } finally {
      saving = false;
    }
  }
</script>

<Modal title="management · {conversation.name}" {close}>
  <p class="dialog-note">Appoint this line's captain and link it to a parent project.</p>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">{error || saved}</div>
  {#if loading}
    <p class="py-5 text-cream-faint">loading management…</p>
  {:else if ready}
    <div class="line-form">
      <label for="captain">captain</label>
      <select id="captain" bind:value={captainId} disabled={appointing}>
        <option value="">none · no captain on this line</option>
        {#each room.attachments.filter(isLive) as process (process.id)}
          <option value={process.id}>{process.name} · {process.adapter}</option>
        {/each}
      </select>
      <div class="line-actions">
        <button class="primary" type="button" disabled={appointing} onclick={appointCaptain}
          >appoint captain</button
        >
      </div>
      {#if parentId}
        <p class="dialog-note">parent line</p>
        <p class="dialog-note">linked to {parentName} · unlink to make it independent</p>
        <div class="line-actions">
          <button type="button" onclick={close}>close</button>
          <button type="button" disabled={saving} onclick={() => saveParent(null)}>unlink parent</button>
        </div>
      {:else}
        <label for="parentLine">parent line</label>
        <select id="parentLine" bind:value={parentId} disabled={saving}>
          <option value="">none · independent line</option>
          {#each room.conversations.filter((line) => line.id !== conversation.id) as line (line.id)}
            <option value={line.id}>{line.name}</option>
          {/each}
        </select>
        <div class="line-actions">
          <button type="button" onclick={close}>close</button>
          <button class="primary" type="button" disabled={saving} onclick={() => saveParent(parentId || null)}
            >save parent</button
          >
        </div>
      {/if}
    </div>
  {:else}
    <button type="button" onclick={close}>close</button>
  {/if}
</Modal>
