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
  let updateCli = $state(false);
  let attaching = $state(false);

  const selectedAdapter = $derived(session.adapters.find((option) => option.id === adapter));
  const updateCommand = $derived(selectedAdapter?.update_command ?? null);
  const canUpdate = $derived(Boolean(updateCommand && updateCommand.length > 0));
  const updateTitle = $derived(
    updateCommand && updateCommand.length > 0
      ? updateCommand.join(" ")
      : "this adapter has no update command",
  );

  // The picker's default follows the registry: an adapter imported from a repo
  // is selectable the moment it registers, without this file knowing its name.
  $effect(() => {
    const firstAdapter = session.adapters.at(0);
    if (!adapter && firstAdapter) adapter = firstAdapter.id;
  });

  function adapterCanUpdate(adapterId: string): boolean {
    const cmd = session.adapters.find((option) => option.id === adapterId)?.update_command;
    return Boolean(cmd && cmd.length > 0);
  }

  function applyPreset(): void {
    const preset = session.presets.find((p) => p.id === presetId);
    if (!preset) return;
    name = preset.name;
    adapter = preset.adapter;
    command = preset.command;
    if (!adapterCanUpdate(adapter)) updateCli = false;
  }

  function onAdapterChosen(): void {
    if (!adapterCanUpdate(adapter)) updateCli = false;
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
        ...(updateCli ? { update: true } : {}),
      });
      // The socket normally announces this too, and `upsertAttachment` is keyed
      // by id so the two cannot double up. Recording it here matters for the
      // case where the socket is mid-reconnect: the process is running either
      // way, and it must not be invisible.
      room.upsertAttachment(attached);
      name = "";
      command = "";
      updateCli = false;
    } catch (error) {
      room.showNotice(error instanceof ApiError ? error.message : "attach failed", "error");
    } finally {
      attaching = false;
    }
  }
</script>

<form id="attach" class="flex flex-col gap-[7px] px-3 pt-1 pb-5" onsubmit={attach}>
  <label for="aPreset" class="mb-[-4px] text-[10px] tracking-[0.05em] text-cream-faint">preset</label>
  <div id="presetRow" class="flex items-center gap-1.5">
    <select id="aPreset" class="min-w-0 flex-1" bind:value={presetId} onchange={applyPreset}>
      <option value="">— none —</option>
      {#each session.presets as preset (preset.id)}
        <option value={preset.id}>{preset.title}</option>
      {/each}
    </select>
    <button
      type="button"
      id="presetSave"
      class="flex-none px-2 py-1.5 text-[10.5px]"
      title="save current name/adapter/command as a preset"
      onclick={() =>
        dialogs.open(PresetDialog, {
          preset: { title: name.trim(), name: name.trim(), adapter, command: command.trim() },
        })}>save</button
    >
    <button
      type="button"
      id="presetManage"
      class="flex-none px-2 py-1.5 text-[10.5px]"
      title="view / edit presets"
      onclick={() => dialogs.open(PresetsDialog)}
    >
      manage
    </button>
  </div>

  <label for="aName" class="mb-[-4px] text-[10px] tracking-[0.05em] text-cream-faint"
    >name (the @handle)</label
  >
  <input id="aName" bind:value={name} placeholder="reviewer" maxlength="32" autocomplete="off" />

  <div class="adapter-row flex items-baseline justify-between">
    <label for="aAdapter" class="mb-[-4px] text-[10px] tracking-[0.05em] text-cream-faint">adapter</label>
    <button
      type="button"
      id="adapterImport"
      title="import adapters from a git repository"
      onclick={() => dialogs.open(ImportAdaptersDialog)}>+ import…</button
    >
  </div>
  <div class="adapter-picker flex items-center gap-1.5">
    <select id="aAdapter" class="min-w-0 flex-1" bind:value={adapter} onchange={onAdapterChosen}>
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

  <label for="aCmd" class="mb-[-4px] text-[10px] tracking-[0.05em] text-cream-faint"
    >command (blank = adapter default)</label
  >
  <input id="aCmd" bind:value={command} placeholder="blank = adapter default" autocomplete="off" />

  <label for="aCwd" class="mb-[-4px] text-[10px] tracking-[0.05em] text-cream-faint">working directory</label>
  <input id="aCwd" bind:value={cwd} placeholder="~/code/myproject" autocomplete="off" />

  <label
    class="update-row flex items-center gap-2 min-h-11 cursor-pointer text-[10px] tracking-[0.05em] text-cream-faint has-[input:disabled]:cursor-default"
    for="aUpdate"
    title={updateTitle}
  >
    update CLI first
    <input
      id="aUpdate"
      class="h-[15px] w-[15px] flex-none p-0 accent-copper"
      type="checkbox"
      bind:checked={updateCli}
      disabled={!canUpdate}
      title={updateTitle}
    />
  </label>

  <button class="primary" type="submit" disabled={attaching}>{attaching ? "attaching…" : "attach"}</button>
  <div class="note text-[10px] italic text-cream-faint">the real interactive process is spawned in a pty</div>
</form>
