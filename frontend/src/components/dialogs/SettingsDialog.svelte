<script lang="ts">
  /** Instance settings that affect the next briefing sent to a process. */
  import { onMount } from "svelte";
  import { tick } from "svelte";
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { getGlobalProse, setGlobalProse } from "../../lib/settings-api";
  import { getResourceSettings, setResourceSettings, type ResourceSettings } from "../../lib/resource-api";
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
  let budgetLoading = $state(true);
  let budgetSaving = $state(false);
  let budgetError = $state("");

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
      reserveGb = budget.memory_reserve_bytes / 1024 ** 3;
      leaseGb = budget.default_process_memory_bytes / 1024 ** 3;
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
        memory_reserve_bytes: Math.round(reserveGb * 1024 ** 3),
        default_process_memory_bytes: Math.round(leaseGb * 1024 ** 3),
      });
      await resources.load();
    } catch (failure: unknown) {
      budgetError = failure instanceof ApiError ? failure.message : "could not save resource settings";
    } finally {
      budgetSaving = false;
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
        )} GB · process lease ceiling {Math.floor(budget.memory_ceiling_bytes / 1024 ** 3)} GB
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
        disabled={budgetLoading || budgetSaving}
      />
      <label for="memoryReserve">memory reserve (GB)</label>
      <input
        id="memoryReserve"
        type="number"
        min="0"
        step="0.25"
        bind:value={reserveGb}
        disabled={budgetLoading || budgetSaving}
      />
      <label for="defaultLease">default process lease (GB)</label>
      <input
        id="defaultLease"
        type="number"
        min="0.25"
        step="0.25"
        bind:value={leaseGb}
        disabled={budgetLoading || budgetSaving}
      />
      <div class="line-status" class:error={Boolean(budgetError)} aria-live="polite">
        {budgetLoading ? "loading resource settings…" : budgetError}
      </div>
      <div class="line-actions">
        <button class="primary" type="submit" disabled={budgetLoading || budgetSaving}>
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
