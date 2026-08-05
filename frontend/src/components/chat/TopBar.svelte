<script lang="ts">
  /** The line's name, and its topic — which is also the way in to editing it. */
  import { room } from "../../state/room.svelte.js";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import TopicDialog from "../dialogs/TopicDialog.svelte";

  const topic = $derived((room.conversation?.topic ?? "").trim());
</script>

<div id="topbar">
  <span id="convname">{room.conversation?.name ?? "—"}</span>
  {#if room.conversation}
    <button
      id="convmeta"
      class:unset={!topic}
      type="button"
      title={topic
        ? `${topic}\n\n(click to edit)`
        : "give this line a topic — agents get it in their briefing"}
      onclick={() => dialogs.open(TopicDialog)}>{topic || "set a topic…"}</button
    >
  {/if}
</div>

<style>
  #topbar {
    padding: 16px 28px;
    border-bottom: 1px solid var(--color-line);
    display: flex;
    align-items: baseline;
    gap: 14px;
  }
  #convname {
    font-family: var(--font-serif);
    font-size: 24px;
    font-weight: 400;
    font-style: italic;
    color: var(--color-cream);
    flex: none;
  }
  /* A button, not a span: it does something when clicked, so it should be
     reachable by keyboard and announced as an action. Styled back down to look
     like the line of text it is. */
  #convmeta {
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    text-align: left;
    color: var(--color-cream-dim);
    font-size: 11.5px;
    font-style: italic;
    min-width: 0;
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
    border-bottom: 1px dashed transparent;
    transition: color 0.15s;
  }
  #convmeta:hover {
    color: var(--color-copper-hot);
    background: none;
    border-bottom-color: rgb(217 142 74 / 0.4);
  }
  #convmeta.unset {
    color: var(--color-cream-faint);
  }
</style>
