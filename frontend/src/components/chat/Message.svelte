<script lang="ts">
  /**
   * One line in the feed.
   *
   * `{@html}` is safe here and only here: `renderMessage` escapes the body,
   * parses it, and runs the result through DOMPurify. Nothing else in this app
   * should reach for `{@html}` on a message body.
   */
  import { renderMessage, senderColor } from "../../lib/markdown";
  import { enhanceMarkdown } from "../../lib/message-enhancers";
  import { visibleMessageBody } from "../../lib/files";
  import ImageGrid from "./ImageGrid.svelte";
  import FileAttachments from "./FileAttachments.svelte";
  import Reactions from "./Reactions.svelte";
  import MessageActions from "./MessageActions.svelte";
  import PinIcon from "../PinIcon.svelte";
  import { room } from "../../state/room.svelte.js";
  import type { ReactionEmoji } from "../../lib/reaction-contracts";
  import type { ChatMessage } from "../../lib/contracts";
  import "../../styles/message.css";

  interface Props {
    message: ChatMessage;
  }

  let { message }: Props = $props();

  const isSystem = $derived(message.sender_type === "system");
  const body = $derived(
    renderMessage(
      visibleMessageBody(message),
      message.sender_type === "agent" ? true : message.sender_type === "human" ? "human" : false,
    ),
  );
  const images = $derived(message.files.filter((file) => file.kind === "image"));
  const otherFiles = $derived(message.files.filter((file) => file.kind !== "image"));
  const when = $derived(
    new Date(message.created_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  );
  // Operational notices include multiline update and reattachment reports.
  // Their whitespace contract is the same as human-authored bodies.
  const bodyClass = $derived(
    isSystem
      ? "inline-block max-w-full whitespace-pre-wrap border-y border-dashed border-line px-[18px] py-[3px] text-[11px] text-cream-faint italic [overflow-wrap:anywhere]"
      : message.sender_type === "agent"
        ? "whitespace-normal break-words text-cream"
        : "whitespace-pre-wrap break-words text-cream",
  );
  const rootClass = $derived(isSystem ? "max-w-none text-center my-[18px]" : "max-w-[860px] mb-[14px]");
  // Said on another line of the tree: the relay tags it so a reader knows the
  // speaker is not here, and that only the addressed process was shown it.
  const via = $derived(
    message.source_conv_id && message.source_conv_id !== message.conv_id ? message.source_conv_name : null,
  );
  const isPrivate = $derived(Boolean(message.audience_attachment_id));
</script>

<div
  class="msg group relative animate-[arrive_0.28s_ease_both] {rootClass}"
  class:jump-highlighted={room.history.highlightedId === message.id}
  data-message-id={message.id}
>
  {#if !isSystem}
    <div class="head mb-0.5 flex items-baseline gap-2.5">
      <span
        class="who font-semibold text-[12.5px] {message.sender_type}"
        style:color={senderColor(message.sender, message.sender_type)}
      >
        {message.sender}
      </span>
      <span class="when text-[10px] text-cream-faint">{when}</span>
      {#if via}
        <span class="via text-[10px] text-cream-faint italic">via «{via}»</span>
      {/if}
      {#if isPrivate}
        <span class="direct text-[10px] text-cream-faint">· direct</span>
      {/if}
      {#if room.pins.has(message.id)}
        <span
          class="flex items-center gap-0.5 rounded border border-copper/40 px-1 text-[9px] text-copper-hot"
          ><PinIcon pinned class="size-3" /> pinned</span
        >
      {/if}
      <MessageActions {message} {isSystem} />
    </div>
  {:else}
    <MessageActions {message} {isSystem} />
  {/if}
  <div class="body {bodyClass}" use:enhanceMarkdown={body}>
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitised in renderMessage -->
    {@html body}
  </div>
  {#if !isSystem}
    <Reactions
      messageId={message.id}
      reactions={message.reactions ?? []}
      showControl={false}
      onToggle={(emoji: ReactionEmoji) => room.toggleReaction(message.id, emoji)}
    />
  {/if}
  {#if images.length}
    <ImageGrid {images} />
  {/if}
  {#if otherFiles.length}
    <FileAttachments files={otherFiles} />
  {/if}
</div>
