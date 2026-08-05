<script lang="ts">
  /**
   * Pull adapter packages from a git repository.
   *
   * The warning is not boilerplate: an imported adapter is Python that runs as
   * you, in your shell, with your files. It gets the same prominence as the
   * field it is warning about.
   */
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import { session } from "../../state/session.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  let repository = $state("");
  let ref = $state("");
  let status = $state("");
  let failed = $state(false);
  let busy = $state(false);
  let doneTimer: ReturnType<typeof setTimeout> | null = null;

  async function go(): Promise<void> {
    if (!repository.trim()) return;
    busy = true;
    failed = false;
    status = "cloning…";
    try {
      const result = await api.importAdapters(repository.trim(), ref.trim());
      await session.loadAdapters();
      status = "loaded: " + result.loaded.join(", ");
      doneTimer = setTimeout(close, 1200);
    } catch (error: unknown) {
      status = error instanceof ApiError ? error.message : "import failed";
      failed = true;
      busy = false;
    }
  }

  // Closing during the "loaded" pause must not leave a timer to reopen-close a
  // dialog that is already gone.
  $effect(() => () => {
    if (doneTimer !== null) clearTimeout(doneTimer);
  });
</script>

<Modal title="import adapters" {close}>
  <div class="grid">
    <label for="iRepo">repository</label>
    <input id="iRepo" bind:value={repository} placeholder="https://github.com/you/partyline-adapters.git" />
    <label for="iRef">ref (optional)</label>
    <input id="iRef" bind:value={ref} placeholder="main" />
  </div>

  <p class="dialog-note">Imported adapters run as you, unsandboxed. Only import code you trust.</p>

  <div class="actions">
    <button type="button" class="primary" disabled={busy} onclick={go}>import</button>
  </div>

  <p class="line-status" class:error={failed} aria-live="polite">{status}</p>
</Modal>

<style>
  .grid {
    display: grid;
    grid-template-columns: 110px 1fr;
    gap: 6px 10px;
    align-items: center;
  }
  label {
    color: var(--color-cream-faint);
    font-size: 10px;
    letter-spacing: 0.05em;
    text-align: right;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
  }
</style>
