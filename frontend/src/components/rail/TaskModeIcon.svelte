<script lang="ts">
  import type { Conversation } from "../../lib/contracts";
  import { taskModeInfo } from "../../lib/task-mode";
  import { tooltip } from "../../lib/tooltip";
  interface Props {
    line: Pick<Conversation, "task_status" | "task_mode">;
  }
  let { line }: Props = $props();
  const info = $derived(taskModeInfo(line));
</script>

{#if info}
  <span
    class="task-mode task-mode-{info.mode} inline-flex flex-none items-center {info.tone}"
    role="img"
    aria-label={info.tooltip}
    use:tooltip={{ label: info.tooltip }}
  >
    <svg
      viewBox="0 0 16 16"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      {#if info.mode === "express"}
        <path d="M9 1.5 3.5 9H8l-1 5.5L12.5 7H8z" fill="currentColor" />
      {:else if info.mode === "light"}
        <path d="M13.5 2.5c-5 0-8 2.5-8 7l-2 4M13.5 2.5c0 4-2.5 7-8 7M7 9l3-3M5.5 11l3-3" />
      {:else}
        <path d="M8 1.5 13 3.5v4.2c0 3-2 5.2-5 6.8-3-1.6-5-3.8-5-6.8V3.5z" />
      {/if}
    </svg>
  </span>
{/if}
