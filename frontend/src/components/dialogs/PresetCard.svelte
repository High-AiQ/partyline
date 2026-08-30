<script lang="ts">
  /** One saved attach configuration, editable in place. */
  import { adapterLabel } from "../../lib/attachments";
  import { ApiError, api } from "../../lib/api";
  import type { PresetDraft } from "../../lib/api";
  import type { Preset } from "../../lib/contracts";
  import { session } from "../../state/session.svelte.js";

  interface Props {
    preset: PresetDraft;
    onsaved?: (_preset: Preset) => void;
    onremoved?: (_preset: PresetDraft) => void;
  }

  let { preset, onsaved, onremoved }: Props = $props();

  // Seeded from the preset, then owned by the form. Each card is keyed by id,
  // so a different preset is a different component instance — there is nothing
  // to stay in sync with.
  /* svelte-ignore state_referenced_locally */
  let title = $state(preset.title);
  /* svelte-ignore state_referenced_locally */
  let name = $state(preset.name);
  /* svelte-ignore state_referenced_locally */
  let adapter = $state(preset.adapter);
  /* svelte-ignore state_referenced_locally */
  let command = $state(preset.command);
  let error = $state("");
  let busy = $state(false);

  async function save(): Promise<void> {
    busy = true;
    error = "";
    try {
      const draft: PresetDraft = {
        title: title.trim(),
        name: name.trim(),
        adapter,
        command: command.trim(),
      };
      if (preset.id) draft.id = preset.id;
      const saved = await api.savePreset(draft);
      await session.loadPresets();
      onsaved?.(saved);
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "save failed";
    } finally {
      busy = false;
    }
  }

  async function remove(): Promise<void> {
    if (!preset.id) return;
    busy = true;
    try {
      await api.deletePreset(preset.id);
      await session.loadPresets();
      onremoved?.(preset);
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not delete preset";
      busy = false;
    }
  }
</script>

<div class="border border-line rounded-md bg-ink-3 p-3 flex flex-col gap-[7px]">
  <div class="grid grid-cols-[78px_1fr] gap-x-2.5 gap-y-1.5 items-center">
    <label class="text-cream-faint text-[10px] tracking-[0.05em] text-right" for="pTitle-{preset.id ?? 'new'}"
      >title</label
    >
    <input id="pTitle-{preset.id ?? 'new'}" bind:value={title} maxlength="48" />

    <label class="text-cream-faint text-[10px] tracking-[0.05em] text-right" for="pName-{preset.id ?? 'new'}"
      >@handle</label
    >
    <input id="pName-{preset.id ?? 'new'}" bind:value={name} maxlength="32" />

    <label
      class="text-cream-faint text-[10px] tracking-[0.05em] text-right"
      for="pAdapter-{preset.id ?? 'new'}">adapter</label
    >
    <select id="pAdapter-{preset.id ?? 'new'}" bind:value={adapter}>
      {#each session.adapters as option (option.id)}
        <option value={option.id}>{adapterLabel(option.id)}</option>
      {/each}
    </select>

    <label class="text-cream-faint text-[10px] tracking-[0.05em] text-right" for="pCmd-{preset.id ?? 'new'}"
      >command</label
    >
    <input id="pCmd-{preset.id ?? 'new'}" bind:value={command} placeholder="blank = adapter default" />
  </div>

  {#if error}<div class="line-status error">{error}</div>{/if}

  <div class="flex gap-2 justify-end">
    {#if preset.id}
      <button
        type="button"
        class="text-red border-red/40 hover:bg-red hover:border-red hover:text-ink"
        disabled={busy}
        onclick={remove}>delete</button
      >
    {/if}
    <button type="button" class="primary save" disabled={busy} onclick={save}>
      {preset.id ? "save changes" : "create preset"}
    </button>
  </div>
</div>
