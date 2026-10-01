<script lang="ts">
  import { copyText } from "../../lib/clipboard";
  import { ApiError } from "../../lib/http";
  import { tooltip } from "../../lib/tooltip";
  import type { ChatMessage } from "../../lib/contracts";
  import type { ReactionEmoji } from "../../lib/reaction-contracts";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import PinIcon from "../PinIcon.svelte";
  import Reactions from "./Reactions.svelte";

  interface Props {
    message: ChatMessage;
    isSystem: boolean;
  }

  let { message, isSystem }: Props = $props();
  let copied = $state(false);
  let revertTimer: ReturnType<typeof setTimeout> | undefined;
  const pinned = $derived(room.pins.has(message.id));

  async function copy(): Promise<void> {
    if (await copyText(message.body)) {
      copied = true;
      clearTimeout(revertTimer);
      revertTimer = setTimeout(() => {
        copied = false;
      }, 1500);
    }
  }

  async function togglePin(): Promise<void> {
    const conversationId = room.conversation?.id;
    if (!conversationId) return;
    try {
      await room.pins.toggle(conversationId, message.id);
    } catch (error: unknown) {
      room.showNotice(error instanceof ApiError ? error.message : "could not update pin", "error");
    }
  }

  $effect(() => {
    return () => {
      clearTimeout(revertTimer);
    };
  });
</script>

{#if !isSystem}
  <span class="message-actions ml-auto flex items-center gap-1">
    <Reactions
      messageId={message.id}
      reactions={message.reactions ?? []}
      showChips={false}
      onToggle={(emoji: ReactionEmoji) => room.toggleReaction(message.id, emoji)}
    />
    {#if session.signedIn}
      <button
        class="pin grid size-7 place-items-center rounded border p-0 text-[13px] leading-none transition-opacity {pinned
          ? 'border-copper/60 bg-copper/15 text-copper-hot opacity-100'
          : 'border-line bg-ink-2 text-cream-faint opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto'} hover:bg-copper hover:text-ink"
        type="button"
        use:tooltip={{ label: pinned ? "unpin message" : "pin message" }}
        aria-label={pinned ? "unpin message" : "pin message"}
        onclick={() => void togglePin()}><PinIcon {pinned} /></button
      >
    {/if}
    <button
      class="copy grid size-7 place-items-center rounded border border-line bg-ink-2 p-0 text-[13px] leading-none text-cream-faint opacity-0 pointer-events-none transition-opacity hover:bg-copper hover:text-ink group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto"
      type="button"
      use:tooltip={{ label: copied ? "Copied" : "copy message" }}
      aria-label="copy message"
      onclick={copy}
    >
      {#if copied}
        <svg
          class="size-[13px] fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round]"
          viewBox="0 0 24 24"
          aria-hidden="true"><path d="m5 13 4 4L19 7" /></svg
        >
      {:else}
        <svg
          class="size-[13px] fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round]"
          viewBox="0 0 24 24"
          aria-hidden="true"
          ><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg
        >
      {/if}
    </button>
  </span>
{/if}

<style>
  @media (hover: none) {
    .copy,
    .pin {
      opacity: 1;
      pointer-events: auto;
    }
  }
</style>
