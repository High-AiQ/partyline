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
  <div
    id="wireNotice"
    class="fixed left-1/2 top-[18px] z-70 max-w-[min(560px,90vw)] rounded-[5px] border bg-ink-2 px-[14px] py-2 text-[11px] shadow-[0_12px_30px_rgb(0_0_0/0.45)] {room
      .notice.kind === 'error'
      ? 'border-red/55 text-red'
      : 'border-line text-cream-dim'}"
    role="status"
    aria-live="polite"
  >
    {room.notice.message}
  </div>
{/if}

{#if wire.outage}
  <div
    id="wireDown"
    class="fixed left-1/2 top-[18px] z-71 flex max-w-[min(560px,90vw)] items-center gap-[9px] rounded-[5px] border bg-panel px-[14px] py-2 text-[11px] tracking-[0.04em] shadow-[0_12px_30px_rgb(0_0_0/0.45)] {wire
      .outage.stopped
      ? 'border-panel-line text-cream-dim'
      : 'border-red/55 text-red'}"
    role="status"
    aria-live="polite"
  >
    <span class="pulse size-[6px] rounded-full {wire.outage.stopped ? 'stopped bg-cream-faint' : 'bg-red'}"
    ></span><span>{wire.outage.message}</span>
  </div>
{/if}

<style>
  /* The `arrive` and `wire-pulse` animations stay hand-written — the task is
       to keep keyframes and animation declarations in CSS. The centering
       translate is also hand-written, as `transform` rather than Tailwind's
       `translate` property: the `arrive` keyframes animate `transform`, so a
       normal        `transform: translateX(-50%)` is overridden by the animation
       (leaving the banner offset), while v4's separate `translate` longhand
       would survive it and shift the banner to a centred position — a pixel
       difference in exactly the states (19-wire-notice, 20-wire-down) the
       parity harness now covers. */
  #wireNotice,
  #wireDown {
    transform: translateX(-50%);
    animation: arrive 0.2s ease both;
  }
  .pulse {
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
  .pulse.stopped {
    animation: none;
  }
</style>
