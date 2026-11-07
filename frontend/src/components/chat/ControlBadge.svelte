<script lang="ts">
  /**
   * The agent-control badge: a pink pulsing dot and a small monitor.
   *
   * With `handle` it answers "does this process hold control?" for process
   * lists; without, it is the share status's "an agent is controlling" mark.
   * It renders nothing unless the server reports an active grant, so it goes
   * away on the same event that revokes control or ends the share.
   */
  import { controlBadge } from "../../lib/screen-control";
  import { tooltip } from "../../lib/tooltip";
  import { room } from "../../state/room.svelte.js";

  let { handle }: { handle?: string } = $props();
  const badge = $derived(controlBadge(room.screenShare, handle));
</script>

{#if badge}
  <span
    class="control-badge inline-flex flex-none items-center gap-1 text-pink"
    role="img"
    aria-label={badge.label}
    use:tooltip={{ label: badge.label }}
  >
    <span class="control-dot h-[6px] w-[6px] rounded-full bg-pink shadow-[0_0_7px_var(--color-pink)]"></span>
    <svg
      viewBox="0 0 16 16"
      width="13"
      height="13"
      fill="none"
      stroke="currentColor"
      stroke-width="1.4"
      aria-hidden="true"
    >
      <rect x="1.5" y="2.5" width="13" height="8.5" rx="1" />
      <path d="M5.5 14h5M8 11v3" stroke-linecap="round" />
    </svg>
  </span>
{/if}

<style>
  .control-dot {
    animation: control-pulse 1.1s ease-in-out infinite;
  }
  @keyframes control-pulse {
    50% {
      opacity: 0.25;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .control-dot {
      animation: none;
    }
  }
</style>
