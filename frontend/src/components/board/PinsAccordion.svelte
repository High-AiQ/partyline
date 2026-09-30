<script lang="ts">
  import { ApiError } from "../../lib/http";
  import { storePinAccordionOpen, storedPinAccordionOpen } from "../../lib/pin-accordion-state";
  import { tooltip } from "../../lib/tooltip";
  import type { Pin } from "../../lib/pin-contracts";
  import { room } from "../../state/room.svelte.js";

  let expanded = $state(true);
  let editingId = $state<number | null>(null);
  let aliasDraft = $state("");
  $effect(() => {
    const conversationId = room.conversation?.id;
    if (conversationId) expanded = storedPinAccordionOpen(conversationId);
  });

  function toggled(event: Event): void {
    const node = event.currentTarget;
    const conversationId = room.conversation?.id;
    if (!(node instanceof HTMLDetailsElement) || !conversationId) return;
    expanded = node.open;
    storePinAccordionOpen(conversationId, node.open);
  }

  function startAlias(pin: Pin): void {
    editingId = pin.message_id;
    aliasDraft = pin.alias ?? "";
  }

  async function saveAlias(pin: Pin): Promise<void> {
    const conversationId = room.conversation?.id;
    if (!conversationId) return;
    try {
      await room.pins.alias(conversationId, pin.message_id, aliasDraft.trim() || null);
      editingId = null;
    } catch (error: unknown) {
      room.showNotice(error instanceof ApiError ? error.message : "could not save pin alias", "error");
    }
  }

  async function remove(pin: Pin): Promise<void> {
    const conversationId = room.conversation?.id;
    if (!conversationId) return;
    try {
      await room.pins.remove(conversationId, pin.message_id);
    } catch (error: unknown) {
      room.showNotice(error instanceof ApiError ? error.message : "could not remove pin", "error");
    }
  }

  function jump(pin: Pin): void {
    if (!pin.message_available) return;
    void room.jumpToMessage(pin.message_id).catch((error: unknown) => {
      room.showNotice(error instanceof ApiError ? error.message : "could not load pinned message", "error");
    });
  }
</script>

<details class="px-3 pb-2" bind:open={expanded} ontoggle={toggled}>
  <summary
    class="flex cursor-pointer list-none items-center justify-between px-2 py-2 font-serif text-[16px] italic text-cream-dim"
  >
    <span>pinned messages</span>
    <span class="font-mono text-[10px] not-italic text-cream-faint">{room.pins.items.length}</span>
  </summary>
  {#if room.pins.items.length}
    <ul class="m-0 grid list-none gap-1 p-0">
      {#each room.pins.items as pin (pin.message_id)}
        {@const label = pin.alias ?? pin.message_text ?? "message unavailable"}
        <li
          class="grid grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-1 rounded border border-line bg-ink-3 px-2 py-1.5"
          data-pin-row={pin.message_id}
        >
          {#if editingId === pin.message_id}
            <input
              class="min-w-0 rounded border border-line bg-ink px-1 py-0.5 font-mono text-[10px] text-cream"
              aria-label="pin alias"
              maxlength="120"
              bind:value={aliasDraft}
              onkeydown={(event) => {
                if (event.key === "Enter") void saveAlias(pin);
                if (event.key === "Escape") editingId = null;
              }}
            />
            <button
              class="grid size-6 place-items-center rounded border border-line text-[11px] text-cream-faint hover:bg-copper hover:text-ink"
              type="button"
              use:tooltip={{ label: "save alias" }}
              aria-label="save pin alias"
              onclick={() => void saveAlias(pin)}>✓</button
            >
          {:else}
            <button
              class="min-w-0 cursor-pointer border-0 bg-transparent p-0 text-left text-[10.5px] leading-[1.35] text-cream hover:text-copper-hot disabled:cursor-default disabled:text-cream-faint"
              type="button"
              disabled={!pin.message_available}
              onclick={() => {
                jump(pin);
              }}
            >
              <span
                class="line-clamp-2 [overflow-wrap:anywhere]"
                use:tooltip={{ label: pin.message_available ? label : `${label} · source unavailable` }}
                >{label}{pin.message_available ? "" : " · source unavailable"}</span
              >
            </button>
            <button
              class="grid size-6 place-items-center rounded border border-line text-[11px] text-cream-faint hover:bg-copper hover:text-ink"
              type="button"
              use:tooltip={{ label: pin.alias ? "edit or clear alias" : "add alias" }}
              aria-label="edit pin alias"
              onclick={() => {
                startAlias(pin);
              }}>✎</button
            >
          {/if}
          <button
            class="grid size-6 place-items-center rounded border border-line text-[11px] text-cream-faint hover:bg-red hover:text-ink"
            type="button"
            use:tooltip={{ label: "remove pin" }}
            aria-label="remove pin"
            onclick={() => void remove(pin)}>×</button
          >
        </li>
      {/each}
    </ul>
  {:else}
    <p class="m-0 px-2 pb-1 text-[10px] italic text-cream-faint">pin a message to keep it close</p>
  {/if}
</details>
