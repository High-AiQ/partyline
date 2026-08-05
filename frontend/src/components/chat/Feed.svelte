<script lang="ts">
  /**
   * The line's history.
   *
   * Scroll behaviour is the whole job here: the feed follows new messages only
   * when you are already at the bottom. Someone reading back through history
   * must not be yanked to the end because a process said something.
   */
  import Message from "./Message.svelte";
  import { room } from "../../state/room.svelte.js";

  let feed = $state<HTMLDivElement | null>(null);
  /** Within this much of the bottom counts as "following". */
  const STICK_PX = 140;
  let wasFollowing = true;

  /**
   * `$effect.pre` runs *before* Svelte writes the new message to the DOM, which
   * is the only moment this question can be answered honestly. A plain
   * `$effect` runs after, by which point a tall message has already pushed
   * `scrollHeight` out from under us and a reader who was at the bottom looks
   * like one who had scrolled away — so the feed would stop following exactly
   * when the message was big enough to matter.
   */
  $effect.pre(() => {
    room.messages.length;
    wasFollowing = !feed || feed.scrollHeight - feed.scrollTop - feed.clientHeight < STICK_PX;
  });

  $effect(() => {
    room.messages.length;
    if (wasFollowing && feed) feed.scrollTop = feed.scrollHeight;
  });

  // Opening a line always lands at the newest message, whatever the previous
  // line's scroll position happened to be.
  $effect(() => {
    room.conversation?.id;
    wasFollowing = true;
    if (feed) feed.scrollTop = feed.scrollHeight;
  });
</script>

<div id="feed" bind:this={feed}>
  {#if !room.conversation}
    <div class="empty">
      <div class="art">no line selected</div>
      pick a conversation, or open a new one
    </div>
  {:else if !room.messages.length}
    <div class="empty">
      <div class="art">the line is open</div>
      patch in a process on the right, or just start talking
    </div>
  {:else}
    {#each room.messages as message (message.id)}
      <Message {message} />
    {/each}
  {/if}
</div>

<style>
  #feed {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 22px 28px 10px;
  }
  .empty {
    color: var(--color-cream-faint);
    text-align: center;
    margin-top: 12vh;
    font-size: 12.5px;
  }
  .art {
    font-family: var(--font-serif);
    font-style: italic;
    font-size: 26px;
    color: var(--color-cream-dim);
    margin-bottom: 10px;
  }
</style>
