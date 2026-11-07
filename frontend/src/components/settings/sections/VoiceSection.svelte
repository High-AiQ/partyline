<script lang="ts">
  /**
   * Speech recognizers. Everyone picks which one their mic uses (per browser);
   * the list below is the server's: add, edit, test, order, default, delete.
   * Config-file presets are read-only here, but "customize" saves a settings
   * copy under the same name, which wins over the file until it is deleted.
   */
  import { onDestroy, onMount, untrack } from "svelte";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import SaveIndicator from "../SaveIndicator.svelte";
  import MicrophoneSetting from "../voice/MicrophoneSetting.svelte";
  import VoicePresetCard from "../voice/VoicePresetCard.svelte";
  import VoicePresetForm from "../voice/VoicePresetForm.svelte";
  import { asrApi } from "../../../lib/asr-api";
  import type { AsrPreset, AsrSettings } from "../../../lib/asr-api";
  import { draftFromPreset, draftToBody } from "../../../lib/asr-preset-form";
  import type { AsrDraft } from "../../../lib/asr-preset-form";
  import { SaveTracker } from "../../../lib/save-state";
  import type { SaveSnapshot } from "../../../lib/save-state";
  import { retryDelay, voicePresets } from "../../../state/voice-presets.svelte.js";
  import { sectionShown } from "../section-shown";

  let settings = $state<AsrSettings | null>(null);
  let loadError = $state("");
  /** "new", a preset name being edited or customized, or null. */
  let editing = $state<string | null>(null);
  let busy = $state(false);
  let actionError = $state("");
  let formError = $state("");
  let micSave = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((next) => (micSave = next));
  const stored = $derived(
    settings?.presets.filter((preset) => preset.editable).map((preset) => preset.name) ?? [],
  );
  const usable = $derived(settings?.presets.filter((preset) => preset.available) ?? []);
  const micUses = $derived(
    voicePresets.listing ? voicePresets.active : (voicePresets.chosen ?? settings?.default ?? null),
  );

  /**
   * Fetch the server's listing on mount and again on every store revision —
   * a live `asr_presets_changed`, a reconnect, or recovery after a failure —
   * so another tab's edits show here at once. Rows are keyed by
   * name, so an open form keeps its draft across a refresh.
   */
  let request = 0;
  let attempt = 0;
  let retry: ReturnType<typeof setTimeout> | null = null;
  const shown = sectionShown("voice");
  function reload(): void {
    if (retry !== null) clearTimeout(retry);
    retry = null;
    const mine = ++request;
    asrApi
      .list()
      .then((next) => {
        if (mine !== request) return;
        settings = next;
        loadError = "";
        attempt = 0;
      })
      .catch((failure: unknown) => {
        if (mine !== request) return;
        loadError = failure instanceof Error ? failure.message : "could not load";
        // Its own backoff: the mic list can be fine while this one failed.
        retry = setTimeout(reload, retryDelay(attempt++));
      });
  }
  $effect(() => {
    void voicePresets.revision;
    untrack(reload);
  });
  // Coming back to the tab after a failure tries again at once.
  $effect(() => {
    if (shown() && untrack(() => loadError)) untrack(reload);
  });
  onMount(() => {
    voicePresets.ensure();
  });
  onDestroy(() => {
    request++;
    if (retry !== null) clearTimeout(retry);
    tracker.dispose();
  });

  /** Every change returns the fresh listing; the mic store reloads too (the broadcast also tells other tabs). */
  async function act(work: () => Promise<AsrSettings>, form = false): Promise<boolean> {
    busy = true;
    actionError = formError = "";
    try {
      const next = await work();
      request++; // a listing fetched before this change is stale now
      settings = next;
      void voicePresets.load();
      return true;
    } catch (failure: unknown) {
      const message = failure instanceof Error ? failure.message : "that did not work";
      if (form) formError = message;
      else actionError = message;
      return false;
    } finally {
      busy = false;
    }
  }

  async function saveDraft(draft: AsrDraft, existing: AsrPreset | null): Promise<void> {
    const body = draftToBody(draft);
    const done = await act(
      () => (existing?.editable ? asrApi.update(draft.name, body) : asrApi.create(draft.name, body)),
      true,
    );
    if (done) editing = null;
  }

  function move(preset: AsrPreset, step: -1 | 1): void {
    const names = [...stored];
    const from = names.indexOf(preset.name);
    const to = from + step;
    if (from < 0 || to < 0 || to >= names.length) return;
    names.splice(to, 0, ...names.splice(from, 1));
    void act(() => asrApi.reorder(names));
  }

  function chooseMic(value: string): void {
    void tracker.run(() => {
      voicePresets.choose(value || null);
      return Promise.resolve();
    });
  }
</script>

<SettingsSection id="voice">
  <SettingRow
    id="setting-voice-microphone"
    label="Microphone"
    control="voiceMicDevice"
    description="Which microphone the composer and Show me record from in this browser. Test shows its live level."
  >
    <MicrophoneSetting />
  </SettingRow>

  <SettingRow
    id="setting-voice-mic"
    label="Use for my mic"
    control="voiceMicPreset"
    description="Which recognizer the composer's microphone uses in this browser. Server default follows the default below."
  >
    <select
      id="voiceMicPreset"
      class="w-full max-w-64 rounded border border-line bg-ink-3 px-2 py-1.5 text-[12.5px] text-cream"
      value={voicePresets.chosen ?? ""}
      disabled={!settings}
      onchange={(event) => {
        chooseMic(event.currentTarget.value);
      }}
    >
      <option value="">server default{settings ? ` (${settings.default})` : ""}</option>
      {#each settings?.presets ?? [] as preset (preset.name)}
        <option value={preset.name} disabled={!preset.available}>
          {preset.name}{preset.available ? "" : " — unavailable"}
        </option>
      {/each}
    </select>
    {#snippet status()}
      <SaveIndicator
        state={micSave}
        idle={voicePresets.chosen && micUses !== voicePresets.chosen
          ? `${voicePresets.chosen} is unavailable; the mic uses ${micUses ?? "nothing"} for now`
          : micUses
            ? `the mic uses ${micUses}`
            : usable.length
              ? ""
              : "no recognizer can run yet"}
      />
    {/snippet}
  </SettingRow>

  <SettingRow
    id="setting-asr-presets"
    label="Speech recognizers"
    description="Changes apply at once, without a restart. Presets from the config file are read-only here; customize one to override it by name."
    stacked
  >
    <p class="line-status" class:error={Boolean(loadError || actionError)} aria-live="polite">
      {loadError || actionError || (!settings ? "loading…" : "")}
    </p>
    <div class="flex flex-col gap-2.5">
      {#each settings?.presets ?? [] as preset (preset.name)}
        {#if editing === preset.name}
          <VoicePresetForm
            initial={draftFromPreset(preset)}
            editing={preset.editable}
            takenNames={stored}
            {busy}
            error={formError}
            onsave={(draft: AsrDraft) => void saveDraft(draft, preset)}
            oncancel={() => (editing = null)}
          />
        {:else}
          <VoicePresetCard
            {preset}
            shown={shown()}
            first={stored[0] === preset.name}
            last={stored.at(-1) === preset.name}
            {busy}
            onedit={() => {
              formError = "";
              editing = preset.name;
            }}
            ondefault={() => void act(() => asrApi.makeDefault(preset.name))}
            onmove={(step: -1 | 1) => {
              move(preset, step);
            }}
            ondelete={() => void act(() => asrApi.remove(preset.name))}
          />
        {/if}
      {/each}
    </div>
  </SettingRow>

  <SettingRow
    id="setting-asr-add"
    label="Add a recognizer"
    description="whisper-1 returns segments and timestamps; gpt-4o-transcribe is more accurate but needs the json format."
    stacked
  >
    {#if editing === "new"}
      <VoicePresetForm
        takenNames={stored}
        {busy}
        error={formError}
        onsave={(draft: AsrDraft) => void saveDraft(draft, null)}
        oncancel={() => (editing = null)}
      />
    {:else}
      <div>
        <button
          type="button"
          class="primary"
          disabled={!settings}
          onclick={() => {
            formError = "";
            editing = "new";
          }}>add recognizer…</button
        >
      </div>
    {/if}
  </SettingRow>

  <SettingRow
    id="setting-asr-keys"
    label="API keys"
    description="Keys never pass through this page and are never stored by Partyline."
    stacked
  >
    <p class="text-[11px] leading-[1.6] text-cream-dim">
      A preset names the environment variable that holds its key, and this page shows only whether it is set.
      To add one, put <code class="text-cream">OPENAI_API_KEY=…</code> in the server's
      <code class="text-cream">.env</code>
      file (or the service's environment, e.g. a systemd <code class="text-cream">Environment=</code> line)
      and restart the server. See <code class="text-cream">docs/voice-input.md</code>.
    </p>
  </SettingRow>
</SettingsSection>
