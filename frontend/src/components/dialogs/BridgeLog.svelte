<script lang="ts">
  /**
   * The bridge audit log as a conversation between the two lines.
   *
   * Bridge messages never travel over the chat socket (people read them only
   * here), so there is no live event to follow: the log loads when opened and
   * again on "refresh", which keeps the view pinned to the newest message when
   * it was already there.
   */
  import { onMount, tick } from "svelte";
  import Modal from "../Modal.svelte";
  import BridgeLogGroup from "./BridgeLogGroup.svelte";
  import { ApiError } from "../../lib/api";
  import { bridgeApi, type Bridge, type BridgeLogEntry } from "../../lib/bridge-api";
  import { arrangeLog, logSides } from "../../lib/bridge-log";
  import { formatDayLabel, formatTime } from "../../lib/message-time";
  import "../../styles/bridge-log.css";

  interface Props {
    bridge: Bridge;
    /** The line whose management dialog opened the log. */
    lineId: string;
    close: () => void;
  }
  let { bridge, lineId, close }: Props = $props();

  let entries = $state<BridgeLogEntry[] | null>(null);
  let failure = $state("");
  let refreshing = $state(false);
  let atEnd = $state(true);
  let scroller = $state<HTMLDivElement | null>(null);

  const sides = $derived(logSides(bridge, lineId));
  const items = $derived(arrangeLog(entries ?? [], sides));
  const count = $derived(entries?.length ?? 0);
  const opened = $derived(`${formatDayLabel(bridge.opened_at, new Date())}, ${formatTime(bridge.opened_at)}`);

  const reduceMotion = (): boolean =>
    typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function measure(): void {
    if (scroller) atEnd = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
  }

  async function toNewest(smooth: boolean): Promise<void> {
    await tick();
    if (!scroller) return;
    const top = scroller.scrollHeight;
    if (smooth && !reduceMotion() && typeof scroller.scrollTo === "function") {
      scroller.scrollTo({ top, behavior: "smooth" });
    } else {
      scroller.scrollTop = top;
    }
    atEnd = true;
  }

  async function load(): Promise<void> {
    const followNewest = entries === null || atEnd;
    const opening = entries === null;
    refreshing = true;
    failure = "";
    try {
      entries = await bridgeApi.log(bridge.id);
      if (followNewest) await toNewest(!opening);
    } catch (error) {
      failure = error instanceof ApiError ? error.message : "could not load the bridge log";
    } finally {
      refreshing = false;
    }
  }

  onMount(() => {
    void load();
  });
</script>

<Modal title="bridge log" panel {close}>
  <div class="bl-root">
    <header class="bl-head">
      <div class="bl-lines">
        <span class="bl-chip bl-mine">«{sides[0].side.conv_name}»</span>
        <span class="bl-swap" aria-label="bridged with">⇄</span>
        <span class="bl-chip bl-theirs">«{sides[1].side.conv_name}»</span>
      </div>
      <div class="bl-meta">
        <span>opened {opened}</span>
        <span aria-hidden="true">·</span>
        <span>{count} {count === 1 ? "message" : "messages"}</span>
        <button type="button" class="bl-refresh" disabled={refreshing} onclick={() => void load()}>
          {refreshing ? "refreshing…" : "refresh"}
        </button>
      </div>
    </header>
    <div class="bl-scroll" bind:this={scroller} onscroll={measure}>
      {#if failure}
        <p class="bl-note bl-error" role="alert">{failure}</p>
      {:else if entries === null}
        <p class="bl-note">loading…</p>
      {:else if entries.length === 0}
        <p class="bl-note">nothing has crossed yet</p>
      {:else}
        <div class="bl-thread">
          {#each items as item, index (item.key)}
            {#if item.kind === "day"}
              <div class="bl-day" role="separator"><span>{item.label}</span></div>
            {:else}
              <BridgeLogGroup group={item} {index} />
            {/if}
          {/each}
        </div>
      {/if}
    </div>
    {#if !atEnd}
      <button type="button" class="bl-newest" onclick={() => void toNewest(true)}>↓ newest</button>
    {/if}
  </div>
</Modal>
