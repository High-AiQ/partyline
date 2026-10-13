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
  const hostLabel = $derived(
    view?.host_used_bytes != null ? `${gb(view.host_used_bytes)}/${gb(view.host_ram_bytes)}` : null,
  );
  const partylineShare = $derived(usageShare(view?.host_ram_bytes, view?.partyline_used_bytes));
  const otherShare = $derived(usageShare(view?.host_ram_bytes, view?.other_used_bytes));

  function usageShare(total: number | null | undefined, part: number | null | undefined): number {
    if (total == null || part == null || total <= 0) return 0;
    return Math.min(100, Math.round((part / total) * 100));
  }

  function gb(bytes: number): string {
    return `${(bytes / 1024 ** 3).toFixed(bytes >= 10 * 1024 ** 3 ? 0 : 1)} GB`;
  }

  function gbText(bytes: number | null | undefined): string {
    return bytes == null ? "—" : gb(bytes);
  }

  onMount(() => {
    void resources.load();
  });

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
      ? `processes ${String(view.live_processes)}/${String(view.max_live_processes)}\nhost ${gbText(view.host_used_bytes)}/${gb(view.host_ram_bytes)} · partyline ${gbText(view.partyline_used_bytes)}\nadmission reservation ${gb(view.memory_reserved_bytes)} of ${gb(view.memory_budget_bytes)}\nmost processes (line + child lines): ${view.busiest_line ?? "none"}${blocked ? "\nnew attaches are blocked until usage drops or the limit is raised" : ""}`
      : "resource capacity loading",
  );
</script>

<div class="resource-wrap">
  <button
    class="resource-trigger topbar-action"
    class:topbar-action-selected={resources.popoverOpen}
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
    <span>
      {view ? String(view.live_processes) : "—"}<span class="resource-limit"
        >/{view ? String(view.max_live_processes) : "—"}</span
      >
    </span>
    {#if hostLabel}
      <span class="resource-host">{hostLabel}</span>
    {/if}
  </button>
  {#if resources.popoverOpen && view}
    <div class="resource-popover" role="dialog" aria-label="resource capacity">
      <div>processes <strong>{view.live_processes}/{view.max_live_processes}</strong></div>
      <div>
        host memory <strong>{gbText(view.host_used_bytes)} / {gb(view.host_ram_bytes)}</strong>
      </div>
      {#if view.host_used_bytes != null}
        <div class="host-bar" role="img" aria-label="host memory used of total">
          <span class="partyline" style="width: {String(partylineShare)}%"></span>
          <span class="other" style="width: {String(otherShare)}%"></span>
        </div>
      {/if}
      <div>available <strong>{gbText(view.host_available_bytes)}</strong></div>
      <div>
        partyline <strong>{gbText(view.partyline_used_bytes)}</strong>
        ({gbText(view.partyline_server_bytes)} server + {gbText(view.partyline_processes_bytes)}
        processes)
      </div>
      {#each view.top_lines as line (line.line_id)}
        <div class="top-line">↳ {line.line} <strong>{gb(line.usage_bytes)}</strong></div>
      {/each}
      <div>
        admission reservation <strong
          >{gb(view.memory_reserved_bytes)} / {gb(view.memory_budget_bytes)}</strong
        >
      </div>
      <div>most processes (line + child lines) <strong>{view.busiest_line ?? "none"}</strong></div>
      {#if view.docker}
        <div class="docker-workloads" data-testid="docker-workloads">
          Docker workloads: outside CLI budgets
          <strong>{view.docker.running} running · {gbText(view.docker.memory_used_bytes)}</strong>
          {#if view.docker.uncapped > 0}
            <span class="docker-flag">{view.docker.uncapped} with no RAM cap</span>
          {/if}
          {#if view.docker.unattributed > 0}
            <span class="docker-note">{view.docker.unattributed} unattributed</span>
          {/if}
        </div>
      {/if}
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
    font: inherit;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    transition:
      color 180ms ease,
      border-color 180ms ease;
  }
  .resource-trigger:not(:hover):not(:active):not(:focus-visible):not(.topbar-action-selected) {
    color: var(--color-green);
  }
  .resource-trigger.warning:not(:hover):not(:active):not(:focus-visible):not(.topbar-action-selected) {
    color: var(--color-copper-hot);
  }
  .resource-trigger.full:not(:hover):not(:active):not(:focus-visible):not(.topbar-action-selected) {
    color: var(--color-red);
  }
  .resource-trigger.over-limit:not(:hover):not(:active):not(:focus-visible):not(.topbar-action-selected) {
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
    stroke: currentColor;
    stroke-opacity: 0.3;
  }
  .resource-ring .fill {
    stroke: currentColor;
    stroke-linecap: round;
    transition: stroke-dashoffset 220ms ease;
  }
  .resource-host {
    color: var(--color-cream);
    opacity: 0.72;
  }
  .host-bar {
    display: flex;
    height: 5px;
    margin: 3px 0 1px;
    overflow: hidden;
    border-radius: 4px;
    background: var(--color-panel-line);
  }
  .host-bar span {
    height: 100%;
  }
  .host-bar .partyline {
    background: var(--color-green);
  }
  .host-bar .other {
    background: var(--color-cream);
    opacity: 0.28;
  }
  .top-line {
    color: var(--color-cream);
    opacity: 0.85;
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
  .docker-workloads {
    margin-top: 4px;
    padding-top: 4px;
    border-top: 1px solid var(--color-panel-line);
  }
  .docker-flag {
    display: block;
    color: var(--color-red);
  }
  .docker-note {
    display: block;
    opacity: 0.72;
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
  @media (max-width: 1200px) {
    .resource-limit {
      display: none;
    }
  }
</style>
