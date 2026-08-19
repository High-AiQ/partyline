<script lang="ts">
  /**
   * The working badge: server-asserted busyness rendered confidently,
   * client-guessed uncertainty rendered as a guess.
   *
   * The treatment (label, dot, pulse, tooltip) is derived in
   * `lib/presence-badge.ts`; this component only draws it and keeps a slow
   * clock so decay re-evaluates without wire traffic.
   */
  import { badgeTreatment } from "../../lib/presence-badge";
  import type { PresenceEntry } from "../../state/presence.svelte.js";

  interface Props {
    entry: PresenceEntry | undefined;
  }

  let { entry }: Props = $props();

  let now = $state(Date.now() / 1000);
  $effect(() => {
    const timer = setInterval(() => {
      now = Date.now() / 1000;
    }, 15_000);
    return () => {
      clearInterval(timer);
    };
  });

  const badge = $derived(badgeTreatment(entry, now));
</script>

{#if badge}
  <span
    class="working {badge.tone} {badge.dot} {badge.pulse}"
    role="status"
    title={badge.tooltip || undefined}><span></span>{badge.label}</span
  >
{/if}

<style>
  .working {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--color-green);
    font-size: 9px;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }
  .copper {
    color: var(--color-copper);
  }
  .working span {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 7px currentColor;
    animation: working-pulse 1s ease-in-out infinite;
  }
  /* speaking, or any state whose pulse is off: the dot stays lit, not blinking */
  .none span {
    animation: none;
  }
  .slow span {
    animation: working-pulse 2.4s ease-in-out infinite;
  }
  /* a guess: outline instead of fill, and no glow to project confidence */
  .hollow span {
    background: transparent;
    border: 1px solid currentColor;
    box-shadow: none;
  }
  @keyframes working-pulse {
    50% {
      opacity: 0.25;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .working span,
    .slow span {
      animation: none;
    }
  }
</style>
