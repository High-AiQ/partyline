<script lang="ts">
  /** The resource budget: six numbers saved together, checked inline before they are sent. */
  import { onDestroy, onMount } from "svelte";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import SaveIndicator from "../SaveIndicator.svelte";
  import { getResourceSettings, resetResourceSettings, setResourceSettings } from "../../../lib/resource-api";
  import type { ResourceSettings } from "../../../lib/resource-api";
  import { displayGb, draftFromSettings, resourceBody, validateResources } from "../../../lib/resource-form";
  import type { ResourceDraft } from "../../../lib/resource-form";
  import { SaveTracker } from "../../../lib/save-state";
  import type { SaveSnapshot } from "../../../lib/save-state";

  let stored = $state<ResourceSettings | null>(null);
  let draft = $state<ResourceDraft | null>(null);
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  let tried = $state(false);
  const tracker = new SaveTracker((next) => (save = next));
  const errors = $derived(draft ? validateResources(draft) : {});
  const shown = $derived(tried ? errors : {});
  const dirty = $derived(
    Boolean(stored && draft && JSON.stringify(draftFromSettings(stored)) !== JSON.stringify(draft)),
  );
  const busy = $derived(!draft || save.phase === "saving");

  onMount(() => {
    getResourceSettings()
      .then(accept)
      .catch((failure: unknown) => {
        save = { phase: "error", message: failure instanceof Error ? failure.message : "could not load" };
      });
  });
  onDestroy(() => {
    tracker.dispose();
  });

  function accept(next: ResourceSettings): ResourceSettings {
    stored = next;
    draft = draftFromSettings(next);
    tried = false;
    return next;
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    tried = true;
    if (!draft || !stored || Object.keys(errors).length) return;
    const body = resourceBody(draft, stored);
    const next = await tracker.run(() => setResourceSettings(body), "could not save resource settings");
    if (next) {
      accept(next);
    }
  }

  async function reset(): Promise<void> {
    const next = await tracker.run(() => resetResourceSettings(), "could not reset resource settings");
    if (next) {
      accept(next);
    }
  }

  type Key = keyof ResourceDraft;
  const FIELDS: {
    key: Key;
    id: string;
    row: string;
    label: string;
    unit: string;
    min: number;
    max?: number;
    step: number;
  }[] = [
    {
      key: "maxLiveProcesses",
      id: "maxLiveProcesses",
      row: "max-live-processes",
      label: "Maximum live processes",
      unit: "",
      min: 4,
      max: 32,
      step: 1,
    },
    {
      key: "memoryReserveGb",
      id: "memoryReserve",
      row: "memory-reserve",
      label: "Memory reserve",
      unit: "GB",
      min: 0,
      step: 0.01,
    },
    {
      key: "defaultLeaseGb",
      id: "defaultLease",
      row: "process-memory",
      label: "Default process memory budget",
      unit: "GB",
      min: 0.25,
      step: 0.01,
    },
    {
      key: "reservationGb",
      id: "memoryReservation",
      row: "memory-reservation",
      label: "Memory reservation",
      unit: "GB",
      min: 0.25,
      step: 0.01,
    },
    {
      key: "warnPercent",
      id: "memoryWarnPercent",
      row: "memory-warning",
      label: "Early memory warning",
      unit: "%",
      min: 50,
      max: 95,
      step: 1,
    },
    {
      key: "captainCeilingGb",
      id: "memoryCaptainCeiling",
      row: "captain-ceiling",
      label: "Captain approval ceiling",
      unit: "GB",
      min: 0.25,
      step: 0.01,
    },
  ];

  function describe(key: Key, settings: ResourceSettings | null): string {
    const defaults = settings?.computed_defaults;
    const gb = (bytes: number | undefined): string =>
      bytes === undefined ? "" : ` Default: ${String(displayGb(bytes))} GB.`;
    switch (key) {
      case "maxLiveProcesses":
        return `How many processes may run at once.${defaults ? ` Default: ${String(defaults.max_live_processes)}.` : ""}`;
      case "memoryReserveGb":
        return `RAM kept back for the host and everything else.${gb(defaults?.memory_reserve_bytes)}`;
      case "defaultLeaseGb":
        return `Per-process soft budget: warnings fire as a process nears and passes it. Linux kills only at a higher emergency backstop (1.5× or +1 GB, within ¾ of RAM); Windows enforces it as a hard limit; macOS is best-effort.${gb(defaults?.default_process_memory_bytes)}`;
      case "reservationGb":
        return `Admission accounting estimate per process; it does not limit the process.${gb(defaults?.memory_reservation_bytes)}`;
      case "warnPercent":
        return "Percent of a budget at which people are warned. Default: 80%.";
      default:
        return "Requests above this need a person. Default: twice the process cap, up to the host ceiling.";
    }
  }
</script>

<SettingsSection id="resources">
  {#snippet actions()}
    {#if stored}
      <p class="text-[10.5px] text-cream-faint">
        host {Math.round(stored.host_ram_bytes / 1024 ** 3)} GB · budget {Math.floor(
          stored.memory_budget_bytes / 1024 ** 3,
        )} GB · cap {Math.floor(stored.memory_ceiling_bytes / 1024 ** 3)} GB
      </p>
    {/if}
  {/snippet}
  <form class="flex flex-col gap-3" onsubmit={submit} novalidate>
    {#each FIELDS as field (field.key)}
      <SettingRow
        id="setting-{field.row}"
        label={field.label}
        control={field.id}
        description={describe(field.key, stored)}
      >
        <div class="flex items-center gap-2">
          {#if draft}
            <input
              id={field.id}
              type="number"
              class="w-28 rounded border bg-ink-3 px-2 py-1.5 text-right text-[12.5px] text-cream {shown[
                field.key
              ]
                ? 'border-red'
                : 'border-line'}"
              min={field.min}
              max={field.max}
              step={field.step}
              bind:value={draft[field.key]}
              disabled={busy}
              aria-invalid={Boolean(shown[field.key])}
              aria-describedby={shown[field.key] ? `${field.id}-error` : undefined}
            />
          {:else}
            <span class="w-28 text-right text-[12px] text-cream-faint">…</span>
          {/if}
          <span class="w-6 text-[11px] text-cream-faint">{field.unit}</span>
        </div>
        {#snippet status()}
          {#if shown[field.key]}<p id="{field.id}-error" class="text-[10.5px] text-red">
              {shown[field.key]}
            </p>{/if}
        {/snippet}
      </SettingRow>
    {/each}
    <div
      class="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-ink py-3"
    >
      <SaveIndicator state={save} idle={!draft ? "loading…" : dirty ? "unsaved changes" : ""} />
      <div class="flex gap-2">
        <button type="button" onclick={() => void reset()} disabled={busy}>reset to defaults</button>
        <button class="primary" type="submit" disabled={busy || !dirty}>save resource budget</button>
      </div>
    </div>
  </form>
</SettingsSection>
