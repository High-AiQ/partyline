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
    class="working {badge.tone} {badge.dot} {badge.pulse} inline-flex items-center gap-1 text-[9px] tracking-[0.04em] whitespace-nowrap"
    class:text-green={badge.tone !== "copper"}
    class:text-copper={badge.tone === "copper"}
    role="status"
    title={badge.tooltip || undefined}
    ><span
      class={badge.dot === "hollow"
        ? "h-[5px] w-[5px] rounded-full bg-transparent border border-current shadow-none"
        : "h-[5px] w-[5px] rounded-full bg-current shadow-[0_0_7px_currentColor]"}
    ></span>{badge.label}</span
  >
{/if}

<style>
  .working span {
    animation: working-pulse 1s ease-in-out infinite;
  }
  /* speaking, or any state whose pulse is off: the dot stays lit, not blinking */
  .none span {
    animation: none;
  }
  .slow span {
    animation: working-pulse 2.4s ease-in-out infinite;
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
