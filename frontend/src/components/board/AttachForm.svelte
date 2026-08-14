<script lang="ts">
  /** Spawn a real interactive process in a pty and put it on this line. */
  import { adapterLabel, overrideExplanation } from "../../lib/attachments";
  import { ApiError, api } from "../../lib/api";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import PresetDialog from "../dialogs/PresetDialog.svelte";
  import PresetsDialog from "../dialogs/PresetsDialog.svelte";
  import ImportAdaptersDialog from "../dialogs/ImportAdaptersDialog.svelte";

  let presetId = $state("");
  let name = $state("");
  let adapter = $state("");
  let command = $state("");
  let cwd = $state("");
  let attaching = $state(false);

  const selectedAdapter = $derived(session.adapters.find((option) => option.id === adapter));

  // The picker's default follows the registry: an adapter imported from a repo
  // is selectable the moment it registers, without this file knowing its name.
  $effect(() => {
    const firstAdapter = session.adapters.at(0);
    if (!adapter && firstAdapter) adapter = firstAdapter.id;
  });

  function applyPreset(): void {
    const preset = session.presets.find((p) => p.id === presetId);
    if (!preset) return;
    name = preset.name;
    adapter = preset.adapter;
    command = preset.command;
  }

  async function attach(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!room.conversation) {
      room.showNotice("open a line first", "error");
      return;
    }
    if (!name.trim()) {
      room.showNotice("give it a handle", "error");
      return;
    }

    attaching = true;
    try {
      const attached = await api.attach(room.conversation.id, {
        name: name.trim(),
        adapter,
        command: command.trim(),
        cwd: cwd.trim(),
      });
      // The socket normally announces this too, and `upsertAttachment` is keyed
      // by id so the two cannot double up. Recording it here matters for the
      // case where the socket is mid-reconnect: the process is running either
      // way, and it must not be invisible.
      room.upsertAttachment(attached);
      name = "";
      command = "";
    } catch (error) {
      room.showNotice(error instanceof ApiError ? error.message : "attach failed", "error");
    } finally {
      attaching = false;
    }
  }
</script>

<form id="attach" onsubmit={attach}>
  <label for="aPreset">preset</label>
  <div id="presetRow">
    <select id="aPreset" bind:value={presetId} onchange={applyPreset}>
      <option value="">— none —</option>
      {#each session.presets as preset (preset.id)}
        <option value={preset.id}>{preset.title}</option>
      {/each}
    </select>
    <button
      type="button"
      id="presetSave"
      title="save current name/adapter/command as a preset"
      onclick={() =>
        dialogs.open(PresetDialog, {
          preset: { title: name.trim(), name: name.trim(), adapter, command: command.trim() },
        })}>save</button
    >
    <button
      type="button"
      id="presetManage"
      title="view / edit presets"
      onclick={() => dialogs.open(PresetsDialog)}
    >
      manage
    </button>
  </div>

  <label for="aName">name (the @handle)</label>
  <input id="aName" bind:value={name} placeholder="reviewer" maxlength="32" autocomplete="off" />

  <div class="adapter-row">
    <label for="aAdapter">adapter</label>
    <button
      type="button"
      id="adapterImport"
      title="import adapters from a git repository"
      onclick={() => dialogs.open(ImportAdaptersDialog)}>+ import…</button
    >
  </div>
  <div class="adapter-picker">
    <select id="aAdapter" bind:value={adapter}>
      {#each session.adapters as option (option.id)}
        <option value={option.id}
          >{adapterLabel(option.id)}{option.overrides_bundled ? " (imported)" : ""}</option
        >
      {/each}
    </select>
    {#if selectedAdapter?.overrides_bundled}
      <span
        class="override-badge"
        title={overrideExplanation(selectedAdapter.id)}
        aria-label={overrideExplanation(selectedAdapter.id)}>imported adapter</span
      >
    {/if}
  </div>

  <label for="aCmd">command (blank = adapter default)</label>
  <input id="aCmd" bind:value={command} placeholder="blank = adapter default" autocomplete="off" />

  <label for="aCwd">working directory</label>
  <input id="aCwd" bind:value={cwd} placeholder="~/code/myproject" autocomplete="off" />

  <button class="primary" type="submit" disabled={attaching}>{attaching ? "attaching…" : "attach"}</button>
  <div class="note">the real interactive process is spawned in a pty</div>
</form>

<style>
  #attach {
    padding: 4px 12px 20px;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  label {
    color: var(--color-cream-faint);
    font-size: 10px;
    letter-spacing: 0.05em;
    margin-bottom: -4px;
  }
  .note {
    color: var(--color-cream-faint);
    font-size: 10px;
    font-style: italic;
  }

  #presetRow {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  #presetRow select {
    flex: 1;
    min-width: 0;
  }
  #presetRow button {
    padding: 6px 8px;
    font-size: 10.5px;
    flex: none;
  }

  .adapter-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .adapter-picker {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .adapter-picker select {
    flex: 1;
    min-width: 0;
  }
</style>
