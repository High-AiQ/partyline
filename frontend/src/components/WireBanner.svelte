<script lang="ts">
  /**
   * Two different things that both live at the top of the screen, kept visually
   * distinct on purpose:
   *
   *   - `#wireNotice` is a toast. Something happened; it goes away.
   *   - `#wireDown` stays up for as long as the wire is actually down. A dropped
   *     server used to look exactly like a slow one.
   */
  import { room } from "../state/room.svelte.js";
  import { wire } from "../state/wire.svelte.js";
</script>

{#if room.notice}
  <div id="wireNotice" class={room.notice.kind} role="status" aria-live="polite">
    {room.notice.message}
  </div>
{/if}

{#if wire.outage}
  <div id="wireDown" class:stopped={wire.outage.stopped} role="status" aria-live="polite">
    <span class="pulse"></span><span class="text">{wire.outage.message}</span>
  </div>
{/if}

<style>
  #wireNotice,
  #wireDown {
    position: fixed;
    left: 50%;
    top: 18px;
    transform: translateX(-50%);
    max-width: min(560px, 90vw);
    padding: 8px 14px;
    border-radius: 5px;
    font-size: 11px;
    box-shadow: 0 12px 30px rgb(0 0 0 / 0.45);
    animation: arrive 0.2s ease both;
  }
  #wireNotice {
    z-index: 70;
    border: 1px solid var(--color-line);
    background: var(--color-ink-2);
    color: var(--color-cream-dim);
  }
  #wireNotice.error {
    color: var(--color-red);
    border-color: rgb(201 111 90 / 0.55);
  }

  #wireDown {
    z-index: 71;
    border: 1px solid rgb(201 111 90 / 0.55);
    background: var(--color-panel);
    color: var(--color-red);
    display: flex;
    align-items: center;
    gap: 9px;
    letter-spacing: 0.04em;
  }
  .pulse {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-red);
    animation: wire-pulse 1.4s ease-in-out infinite;
  }
  @keyframes wire-pulse {
    0%,
    100% {
      opacity: 0.25;
    }
    50% {
      opacity: 1;
    }
  }

  /* A deliberate stop is a known state, not an alarm: keep the banner while
     retrying, but drop the warning colour and pulse until the server returns. */
  #wireDown.stopped {
    color: var(--color-cream-dim);
    border-color: var(--color-panel-line);
  }
  #wireDown.stopped .pulse {
    background: var(--color-cream-faint);
    animation: none;
  }
</style>
