<script lang="ts">
  /**
   * The line's history.
   *
   * Scroll behaviour is the whole job here: the feed follows new messages only
   * when you are already at the bottom. Someone reading back through history
   * must not be yanked to the end because a process said something.
   */
  import { tick } from "svelte";
  import Message from "./Message.svelte";
  import { room } from "../../state/room.svelte.js";

  let feed = $state<HTMLDivElement | null>(null);
  /** Within this much of the bottom counts as "following". */
  const STICK_PX = 140;
  const HISTORY_PX = 120;
  let wasFollowing = true;
  let fetchingHistory = false;

  async function loadOlder(): Promise<void> {
    const element = feed;
    const conversationId = room.conversation?.id;
    if (!element || !conversationId || fetchingHistory || !room.history.hasOlder) return;
    fetchingHistory = true;
    const height = element.scrollHeight;
    const top = element.scrollTop;
    try {
      const added = await room.loadOlderMessages();
      await tick();
      if (added && feed === element && room.conversation?.id === conversationId) {
        element.scrollTop = top + element.scrollHeight - height;
      }
    } catch {
      // The inline retry stays at the top of the feed.
    } finally {
      fetchingHistory = false;
    }
  }

  function onscroll(): void {
    if (feed && feed.scrollTop <= HISTORY_PX) void loadOlder();
  }

  /**
   * `$effect.pre` runs *before* Svelte writes the new message to the DOM, which
   * is the only moment this question can be answered honestly. A plain
   * `$effect` runs after, by which point a tall message has already pushed
   * `scrollHeight` out from under us and a reader who was at the bottom looks
   * like one who had scrolled away — so the feed would stop following exactly
   * when the message was big enough to matter.
   */
  $effect.pre(() => {
    void room.messages.length;
    wasFollowing = !feed || feed.scrollHeight - feed.scrollTop - feed.clientHeight < STICK_PX;
  });

  $effect(() => {
    void room.messages.length;
    if (wasFollowing && feed) feed.scrollTop = feed.scrollHeight;
  });

  // Opening a line always lands at the newest message, whatever the previous
  // line's scroll position happened to be.
  $effect(() => {
    void room.conversation?.id;
    wasFollowing = true;
    if (feed) feed.scrollTop = feed.scrollHeight;
  });

  // A short first page may not create a scrollbar. Keep paging until the
  // viewport fills, then ordinary upward scrolling takes over.
  $effect(() => {
    void room.messages.length;
    void room.history.hasOlder;
    if (feed && feed.scrollHeight <= feed.clientHeight) queueMicrotask(() => void loadOlder());
  });
</script>

<div id="feed" class="min-h-0 flex-1 overflow-y-auto px-7 pt-[22px] pb-2.5" bind:this={feed} {onscroll}>
  {#if !room.conversation}
    <div class="empty mt-[12vh] text-center text-[12.5px] text-cream-faint">
      <div class="art mb-2.5 font-serif text-[26px] italic text-cream-dim">no line selected</div>
      pick a conversation, or open a new one
    </div>
  {:else if !room.messages.length}
    <div class="empty mt-[12vh] text-center text-[12.5px] text-cream-faint">
      <div class="art mb-2.5 font-serif text-[26px] italic text-cream-dim">the line is open</div>
      patch in a process on the right, or just start talking
    </div>
  {:else}
    {#if room.history.loadingOlder}
      <div
        class="history-status mx-auto mb-[14px] block w-fit font-mono text-[11px] text-cream-faint"
        aria-live="polite"
      >
        loading earlier messages…
      </div>
    {:else if room.history.olderError}
      <button
        class="history-status retry mx-auto mb-[14px] block w-fit cursor-pointer border-0 border-b border-copper bg-transparent px-0.5 py-[5px] font-mono text-[11px] text-cream-faint"
        type="button"
        onclick={() => void loadOlder()}>earlier messages could not load · retry</button
      >
    {/if}
    {#each room.messages as message (message.id)}
      <Message {message} />
    {/each}
  {/if}
</div>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
       documented `(max-width: 899px)` narrow breakpoint stays hand-written —
       at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH`. */
  @media (max-width: 899px) {
    #feed {
      padding: 16px 14px 8px;
    }
  }
</style>
