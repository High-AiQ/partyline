<script>
  /** One saved attach configuration, editable in place. */
  import { adapterLabel } from "../../lib/attachments.js";
  import { api } from "../../lib/api.js";
  import { session } from "../../state/session.svelte.js";

  let { preset, onsaved = undefined, onremoved = undefined } = $props();

  // Seeded from the preset, then owned by the form. Each card is keyed by id,
  // so a different preset is a different component instance — there is nothing
  // to stay in sync with.
  /* svelte-ignore state_referenced_locally */
  let title = $state(preset.title ?? "");
  /* svelte-ignore state_referenced_locally */
  let name = $state(preset.name ?? "");
  /* svelte-ignore state_referenced_locally */
  let adapter = $state(preset.adapter ?? session.adapters[0]?.id ?? "");
  /* svelte-ignore state_referenced_locally */
  let command = $state(preset.command ?? "");
  let error = $state("");
  let busy = $state(false);

  async function save() {
    busy = true;
    error = "";
    try {
      const saved = await api.savePreset({
        id: preset.id,
        title: title.trim(),
        name: name.trim(),
        adapter,
        command: command.trim(),
      });
      await session.loadPresets();
      onsaved?.(saved);
    } catch (failure) {
      error = failure.message;
    } finally {
      busy = false;
    }
  }

  async function remove() {
    busy = true;
    try {
      await api.deletePreset(preset.id);
      await session.loadPresets();
      onremoved?.(preset);
    } catch (failure) {
      error = failure.message;
      busy = false;
    }
  }
</script>

<div class="preset-card">
  <div class="grid">
    <label for="pTitle-{preset.id ?? 'new'}">title</label>
    <input id="pTitle-{preset.id ?? 'new'}" bind:value={title} maxlength="48" />

    <label for="pName-{preset.id ?? 'new'}">@handle</label>
    <input id="pName-{preset.id ?? 'new'}" bind:value={name} maxlength="32" />

    <label for="pAdapter-{preset.id ?? 'new'}">adapter</label>
    <select id="pAdapter-{preset.id ?? 'new'}" bind:value={adapter}>
      {#each session.adapters as option (option.id)}
        <option value={option.id}>{adapterLabel(option.id)}</option>
      {/each}
    </select>

    <label for="pCmd-{preset.id ?? 'new'}">command</label>
    <input id="pCmd-{preset.id ?? 'new'}" bind:value={command} placeholder="blank = adapter default" />
  </div>

  {#if error}<div class="line-status error">{error}</div>{/if}

  <div class="actions">
    {#if preset.id}
      <button type="button" class="del" disabled={busy} onclick={remove}>delete</button>
    {/if}
    <button type="button" class="primary save" disabled={busy} onclick={save}>
      {preset.id ? "save changes" : "create preset"}
    </button>
  </div>
</div>

<style>
  .preset-card {
    border: 1px solid var(--color-line);
    border-radius: 6px;
    background: var(--color-ink-3);
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .grid {
    display: grid;
    grid-template-columns: 78px 1fr;
    gap: 6px 10px;
    align-items: center;
  }
  .grid label {
    color: var(--color-cream-faint);
    font-size: 10px;
    letter-spacing: 0.05em;
    text-align: right;
  }
  .actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }
  .del {
    color: var(--color-red);
    border-color: rgb(201 111 90 / 0.4);
  }
  .del:hover {
    background: var(--color-red);
    border-color: var(--color-red);
    color: var(--color-ink);
  }
</style>
