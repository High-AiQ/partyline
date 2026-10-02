<script lang="ts">
  /** Compact fleet-wide admission snapshot beside the account controls. */
  import { onMount } from "svelte";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { resources } from "../../state/resources.svelte.js";
  import { tooltipsEnabled, tooltip } from "../../lib/tooltip";
  import SettingsDialog from "../dialogs/SettingsDialog.svelte";

  const view = $derived(resources.snapshot);
  const ratio = $derived(view ? Math.min(1, view.live_processes / view.max_live_processes) : 0);
  const percent = $derived(Math.round(ratio * 100));
  const blocked = $derived(
    Boolean(
      view &&
      (view.live_processes >= view.max_live_processes ||
        view.memory_reserved_bytes >= view.memory_budget_bytes),
    ),
  );
  const overLimit = $derived(
    Boolean(
      view &&
      (view.live_processes > view.max_live_processes ||
        view.memory_reserved_bytes > view.memory_budget_bytes),
    ),
  );

  onMount(() => {
    void resources.load();
  });

  function gb(bytes: number): string {
    return `${(bytes / 1024 ** 3).toFixed(bytes >= 10 * 1024 ** 3 ? 0 : 1)} GB`;
  }

  function openSettings(): void {
    resources.popoverOpen = false;
    dialogs.open(SettingsDialog, { focusBudget: true });
  }

  function activate(): void {
    if (tooltipsEnabled()) openSettings();
    else resources.popoverOpen = !resources.popoverOpen;
  }

  const tooltipLabel = $derived(
    view
      ? `processes ${String(view.live_processes)}/${String(view.max_live_processes)}\nmemory reserved ${gb(view.memory_reserved_bytes)} of ${gb(view.memory_budget_bytes)} · cap ${gb(view.memory_cap_bytes)}\nmost processes: ${view.busiest_line ?? "none"}${blocked ? "\nnew attaches are blocked until usage drops or the limit is raised" : ""}`
      : "resource capacity loading",
  );
</script>

<div class="resource-wrap">
  <button
    class="resource-trigger topbar-action"
    class:open={resources.popoverOpen}
    class:warning={percent >= 70 && percent < 100}
    class:full={blocked || overLimit}
    class:over-limit={overLimit}
    type="button"
    aria-label={tooltipLabel.replaceAll("\n", ", ")}
    aria-expanded={resources.popoverOpen}
    use:tooltip={{ label: tooltipLabel, placement: "below" }}
    onclick={activate}
  >
    <svg class="resource-ring" viewBox="0 0 20 20" aria-hidden="true">
      <circle class="track" cx="10" cy="10" r="8" />
      <circle
        class="fill"
        cx="10"
        cy="10"
        r="8"
        stroke-dasharray="50.27"
        stroke-dashoffset={50.27 * (1 - ratio)}
      />
    </svg>
    <span>{view ? `${String(view.live_processes)}/${String(view.max_live_processes)}` : "—/—"}</span>
  </button>
  {#if resources.popoverOpen && view}
    <div class="resource-popover" role="dialog" aria-label="resource capacity">
      <div>processes <strong>{view.live_processes}/{view.max_live_processes}</strong></div>
      <div>reserved <strong>{gb(view.memory_reserved_bytes)} / {gb(view.memory_budget_bytes)}</strong></div>
      <div>cap <strong>{gb(view.memory_cap_bytes)}</strong></div>
      <div>most processes <strong>{view.busiest_line ?? "none"}</strong></div>
      {#if blocked}
        <p class="capacity-blocked">New attaches are blocked until usage drops or the limit is raised.</p>
      {/if}
      <button type="button" class="edit-budget" onclick={openSettings}>edit budget</button>
    </div>
  {/if}
</div>

<style>
  .resource-wrap {
    position: relative;
    flex: none;
  }
  .resource-trigger {
    display: flex;
    align-items: center;
    gap: 4px;
    min-height: 34px;
    padding: 0 7px;
    color: var(--color-green);
    font: inherit;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    transition:
      color 180ms ease,
      border-color 180ms ease;
  }
  .resource-trigger.warning {
    color: var(--color-copper-hot);
  }
  .resource-trigger.full {
    color: var(--color-red);
  }
  .resource-trigger.open,
  .resource-trigger.open:hover:not(:disabled),
  .resource-trigger.open:active:not(:disabled) {
    background: var(--color-ink-2);
    border-color: var(--color-line);
  }
  .resource-trigger.open.warning,
  .resource-trigger.open.warning:hover:not(:disabled),
  .resource-trigger.open.warning:active:not(:disabled) {
    color: var(--color-copper-hot);
  }
  .resource-trigger.open.full,
  .resource-trigger.open.full:hover:not(:disabled),
  .resource-trigger.open.full:active:not(:disabled) {
    color: var(--color-red);
  }
  .resource-trigger.over-limit {
    color: var(--color-red);
  }
  .resource-ring {
    width: 16px;
    height: 16px;
    transform: rotate(-90deg);
    overflow: visible;
  }
  .resource-ring circle {
    fill: none;
    stroke-width: 2.5;
  }
  .resource-ring .track {
    stroke: var(--color-line);
  }
  .resource-ring .fill {
    stroke: currentColor;
    stroke-linecap: round;
    transition: stroke-dashoffset 220ms ease;
  }
  .resource-popover {
    position: absolute;
    z-index: 30;
    top: calc(100% + 8px);
    right: 0;
    width: 230px;
    padding: 11px 12px;
    border: 1px solid var(--color-panel-line);
    border-radius: 8px;
    background: var(--color-panel);
    color: var(--color-cream);
    box-shadow: 0 8px 24px #0004;
    font-size: 11px;
    line-height: 1.7;
  }
  .resource-popover strong {
    float: right;
    font-weight: 500;
  }
  .edit-budget {
    margin-top: 7px;
    color: var(--color-copper-hot);
  }
  .capacity-blocked {
    margin-top: 5px;
    color: var(--color-red);
  }
  @media (max-width: 899px) {
    .resource-trigger {
      min-height: 44px;
      padding: 0 5px;
    }
    .resource-popover {
      right: -66px;
    }
  }
</style>
