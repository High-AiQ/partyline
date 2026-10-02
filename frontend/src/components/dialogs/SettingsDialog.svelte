<script lang="ts">
  /** Instance settings that affect the next briefing sent to a process. */
  import { onMount } from "svelte";
  import { tick } from "svelte";
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { getGlobalProse, setGlobalProse } from "../../lib/settings-api";
  import {
    getResourceSettings,
    resetResourceSettings,
    setResourceSettings,
    type ResourceSettings,
  } from "../../lib/resource-api";
  import { resources } from "../../state/resources.svelte.js";

  interface Props {
    close: () => void;
    focusBudget?: boolean;
  }

  let { close, focusBudget = false }: Props = $props();
  const MAX = 10000;
  let value = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let error = $state("");
  let field = $state<HTMLTextAreaElement | null>(null);
  let budgetSection = $state<HTMLElement | null>(null);
  let budget = $state<ResourceSettings | null>(null);
  let maxProcesses = $state(4);
  let reserveGb = $state(2);
  let leaseGb = $state(4);
  let reservationGb = $state(1);
  let warnPercent = $state(80);
  let captainCeilingGb = $state(8);
  let budgetLoading = $state(true);
  let budgetSaving = $state(false);
  let resettingBudget = $state(false);
  let budgetError = $state("");
  const GIB = 1024 ** 3;

  function displayGb(bytes: number): number {
    return Number((bytes / GIB).toFixed(2));
  }

  function bytesForSave(value: number, originalBytes: number): number {
    return displayGb(originalBytes) === Number(value.toFixed(2)) ? originalBytes : Math.round(value * GIB);
  }

  onMount(() => {
    void load();
  });

  async function load(): Promise<void> {
    try {
      value = (await getGlobalProse()).value ?? "";
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not load settings";
    } finally {
      loading = false;
    }
    try {
      budget = await getResourceSettings();
      maxProcesses = budget.max_live_processes;
      reserveGb = displayGb(budget.memory_reserve_bytes);
      leaseGb = displayGb(budget.default_process_memory_bytes);
      reservationGb = displayGb(budget.memory_reservation_bytes);
      warnPercent = budget.memory_warn_percent;
      captainCeilingGb = displayGb(budget.memory_captain_ceiling_bytes);
      if (focusBudget) {
        await tick();
        budgetSection?.scrollIntoView({ block: "center" });
      }
    } catch (failure: unknown) {
      budgetError = failure instanceof ApiError ? failure.message : "could not load resource settings";
    } finally {
      budgetLoading = false;
    }
  }

  async function saveBudget(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (budgetSaving) return;
    budgetSaving = true;
    budgetError = "";
    try {
      budget = await setResourceSettings({
        max_live_processes: maxProcesses,
        memory_reserve_bytes: bytesForSave(reserveGb, budget?.memory_reserve_bytes ?? 0),
        default_process_memory_bytes: bytesForSave(leaseGb, budget?.default_process_memory_bytes ?? 0),
        memory_reservation_bytes: bytesForSave(reservationGb, budget?.memory_reservation_bytes ?? 0),
        memory_warn_percent: warnPercent,
        memory_captain_ceiling_bytes: bytesForSave(
          captainCeilingGb,
          budget?.memory_captain_ceiling_bytes ?? 0,
        ),
      });
      await resources.load();
    } catch (failure: unknown) {
      budgetError = failure instanceof ApiError ? failure.message : "could not save resource settings";
    } finally {
      budgetSaving = false;
    }
  }

  async function resetBudget(): Promise<void> {
    if (budgetSaving || resettingBudget) return;
    resettingBudget = true;
    budgetError = "";
    try {
      budget = await resetResourceSettings();
      maxProcesses = budget.max_live_processes;
      reserveGb = displayGb(budget.memory_reserve_bytes);
      leaseGb = displayGb(budget.default_process_memory_bytes);
      reservationGb = displayGb(budget.memory_reservation_bytes);
      warnPercent = budget.memory_warn_percent;
      captainCeilingGb = displayGb(budget.memory_captain_ceiling_bytes);
      await resources.load();
    } catch (failure: unknown) {
      budgetError = failure instanceof ApiError ? failure.message : "could not reset resource settings";
    } finally {
      resettingBudget = false;
    }
  }

  async function save(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (saving) return;
    saving = true;
    error = "";
    try {
      await setGlobalProse(value);
      close();
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not save global prose";
      saving = false;
    }
  }
</script>

<Modal title="settings" {close}>
  <section id="resource-budget" bind:this={budgetSection} class="mb-5 border-b border-line pb-4">
    <h2 class="mb-2 text-[12px] text-cream">resource budget</h2>
    {#if budget}
      <p class="dialog-note mb-2">
        host {Math.round(budget.host_ram_bytes / 1024 ** 3)} GB · available after reserve {Math.floor(
          budget.memory_budget_bytes / 1024 ** 3,
        )} GB · process cap ceiling {Math.floor(budget.memory_ceiling_bytes / 1024 ** 3)} GB
      </p>
    {/if}
    <form class="line-form" onsubmit={saveBudget}>
      <label for="maxLiveProcesses">maximum live processes</label>
      <input
        id="maxLiveProcesses"
        type="number"
        min="4"
        max="32"
        step="1"
        bind:value={maxProcesses}
        disabled={budgetLoading || budgetSaving || resettingBudget}
      />
      {#if budget}
        <p class="dialog-note">default: {budget.computed_defaults.max_live_processes}</p>
      {/if}
      <label for="memoryReserve">memory reserve (GB)</label>
      <input
        id="memoryReserve"
        type="number"
        min="0"
        step="0.01"
        bind:value={reserveGb}
        disabled={budgetLoading || budgetSaving || resettingBudget}
      />
      {#if budget}
        <p class="dialog-note">
          default: {displayGb(budget.computed_defaults.memory_reserve_bytes)} GB
        </p>
      {/if}
      <label for="defaultLease">default process memory cap (GB)</label>
      <input
        id="defaultLease"
        type="number"
        min="0.25"
        step="0.01"
        bind:value={leaseGb}
        disabled={budgetLoading || budgetSaving || resettingBudget}
      />
      {#if budget}
        <p class="dialog-note">
          Per-process kernel kill threshold; default: {displayGb(
            budget.computed_defaults.default_process_memory_bytes,
          )} GB
        </p>
      {/if}
      <label for="memoryReservation">memory reservation (GB)</label>
      <input
        id="memoryReservation"
        type="number"
        min="0.25"
        step="0.01"
        bind:value={reservationGb}
        disabled={budgetLoading || budgetSaving || resettingBudget}
      />
      {#if budget}
        <p class="dialog-note">
          Admission accounting estimate per process; it does not limit the process. default: {displayGb(
            budget.computed_defaults.memory_reservation_bytes,
          )} GB
        </p>
      {/if}
      <label for="memoryWarnPercent">early memory warning (%)</label>
      <input
        id="memoryWarnPercent"
        type="number"
        min="50"
        max="95"
        step="1"
        bind:value={warnPercent}
        disabled={budgetLoading || budgetSaving || resettingBudget}
      />
      <p class="dialog-note">People only · default: 80%</p>
      <label for="memoryCaptainCeiling">captain approval ceiling (GB)</label>
      <input
        id="memoryCaptainCeiling"
        type="number"
        min="0.25"
        step="0.01"
        bind:value={captainCeilingGb}
        disabled={budgetLoading || budgetSaving || resettingBudget}
      />
      <p class="dialog-note">
        Requests above this ceiling need a person · default: twice the process cap, up to the host ceiling
      </p>
      <div class="line-status" class:error={Boolean(budgetError)} aria-live="polite">
        {budgetLoading ? "loading resource settings…" : budgetError}
      </div>
      <div class="line-actions">
        <button
          type="button"
          onclick={resetBudget}
          disabled={budgetLoading || budgetSaving || resettingBudget}
        >
          {resettingBudget ? "resetting…" : "reset to defaults"}
        </button>
        <button class="primary" type="submit" disabled={budgetLoading || budgetSaving || resettingBudget}>
          {budgetSaving ? "saving…" : "save resource budget"}
        </button>
      </div>
    </form>
  </section>
  <p class="dialog-text">
    This text is added after the opening line of every process briefing. Changes apply when a process next
    joins or resumes.
  </p>
  <form id="globalProseForm" class="line-form" onsubmit={save}>
    <label for="globalProse">global prose</label>
    <textarea
      id="globalProse"
      bind:this={field}
      bind:value
      rows={8}
      maxlength={MAX}
      disabled={loading || saving}
      placeholder="shared instructions for every process…"></textarea>
    <p class="dialog-note">{value.length} / {MAX} characters</p>
    <div class="line-status" class:error={Boolean(error)} aria-live="polite">
      {loading ? "loading settings…" : error}
    </div>
    <div class="line-actions">
      <button type="button" onclick={close}>cancel</button>
      <button class="primary" type="submit" disabled={loading || saving}>
        {saving ? "saving…" : "save settings"}
      </button>
    </div>
  </form>
</Modal>
