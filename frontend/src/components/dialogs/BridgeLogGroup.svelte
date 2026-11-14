<script lang="ts">
  /** One run of consecutive bridge messages from one side: avatar, line chip, bubbles. */
  import { renderMessage } from "../../lib/markdown";
  import { enhanceMarkdown } from "../../lib/message-enhancers";
  import { monogram, stripBridgeAddress, type LogGroup } from "../../lib/bridge-log";
  import { formatFull, formatTime, isoInstant } from "../../lib/message-time";
  import { tooltip } from "../../lib/tooltip";
  import "../../styles/message.css";

  interface Props {
    group: LogGroup;
    /** Position in the log, to stagger the entrance of the first screenful. */
    index: number;
  }
  let { group, index }: Props = $props();

  const side = $derived(group.speaker);
  const first = $derived(group.entries[0]);
  const direction = $derived(side.mine ? "leaves this line" : "arrives at this line");
</script>

<article
  class="bl-group {side.mine ? 'bl-mine' : 'bl-theirs'}"
  style:--bl-delay="{Math.min(index, 8) * 45}ms"
  aria-label="{side.side.name} on «{side.side.conv_name}», {direction}"
>
  <div class="bl-avatar" aria-hidden="true">{monogram(side.side.conv_name)}</div>
  <div class="bl-column">
    <header class="bl-who">
      <span class="bl-chip">«{side.side.conv_name}»</span>
      <span class="bl-handle">{side.side.name}</span>
      <span class="bl-arrow" use:tooltip={{ label: direction }}>{side.arrow}</span>
      {#if first}
        <time datetime={isoInstant(first.created_at)} use:tooltip={{ label: formatFull(first.created_at) }}
          >{formatTime(first.created_at)}</time
        >
      {/if}
    </header>
    {#each group.entries as entry (entry.id)}
      <div class="bl-bubble">
        <div class="body bl-body" use:enhanceMarkdown={entry.body}>
          <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitised in renderMessage -->
          {@html renderMessage(stripBridgeAddress(entry.body), true)}
        </div>
        {#if group.entries.length > 1}
          <time class="bl-stamp" datetime={isoInstant(entry.created_at)}>{formatTime(entry.created_at)}</time>
        {/if}
      </div>
    {/each}
  </div>
</article>
