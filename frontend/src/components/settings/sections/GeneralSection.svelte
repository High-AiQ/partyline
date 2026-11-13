<script lang="ts">
  /** The instance label (read-only, from config) and the global prose every briefing carries. */
  import { onDestroy, onMount } from "svelte";
  import ReviewEnvironments from "./ReviewEnvironments.svelte";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import SaveIndicator from "../SaveIndicator.svelte";
  import { getGlobalProse, setGlobalProse } from "../../../lib/settings-api";
  import { SaveTracker } from "../../../lib/save-state";
  import type { SaveSnapshot } from "../../../lib/save-state";
  import { session } from "../../../state/session.svelte.js";

  const MAX = 10000;
  let value = $state("");
  let saved = $state("");
  let loading = $state(true);
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((next) => (save = next));
  const dirty = $derived(value !== saved);

  onMount(() => {
    getGlobalProse()
      .then((prose) => {
        value = saved = prose.value ?? "";
      })
      .catch((failure: unknown) => {
        save = { phase: "error", message: failure instanceof Error ? failure.message : "could not load" };
      })
      .finally(() => (loading = false));
  });
  onDestroy(() => {
    tracker.dispose();
  });

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const stored = await tracker.run(() => setGlobalProse(value), "could not save global prose");
    if (stored) value = saved = stored.value ?? "";
  }
</script>

<SettingsSection id="general">
  <SettingRow
    id="setting-instance-name"
    label="Instance name"
    description="Shown above every line so you can tell servers apart. Set it with --instance-name, PARTYLINE_INSTANCE_NAME, or [instance] name in the config file."
  >
    <span class="text-[12.5px] {session.instanceName ? 'text-copper-hot' : 'text-cream-faint italic'}"
      >{session.instanceName ?? "not set"}</span
    >
  </SettingRow>
  <SettingRow
    id="setting-global-prose"
    label="Global prose"
    control="globalProse"
    description="Added after the opening line of every process briefing. Changes apply when a process next joins or resumes."
    stacked
  >
    <form id="globalProseForm" class="flex flex-col gap-2" onsubmit={submit}>
      <textarea
        id="globalProse"
        bind:value
        rows={8}
        maxlength={MAX}
        disabled={loading || save.phase === "saving"}
        class="w-full rounded border border-line bg-ink-3 p-3 text-[12.5px] leading-[1.55] text-cream"
        placeholder="shared instructions for every process…"></textarea>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-[10.5px] text-cream-faint">{value.length} / {MAX} characters</span>
        <div class="flex gap-2">
          <button type="button" disabled={!dirty || save.phase === "saving"} onclick={() => (value = saved)}
            >revert</button
          >
          <button class="primary" type="submit" disabled={loading || !dirty || save.phase === "saving"}
            >save prose</button
          >
        </div>
      </div>
      <SaveIndicator state={save} idle={loading ? "loading…" : dirty ? "unsaved changes" : ""} />
    </form>
  </SettingRow>
  <ReviewEnvironments />
</SettingsSection>
