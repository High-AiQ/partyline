<script lang="ts">
  /** Instance settings that affect the next briefing sent to a process. */
  import { onMount } from "svelte";
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { getGlobalProse, setGlobalProse } from "../../lib/settings-api";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();
  const MAX = 10000;
  let value = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let error = $state("");
  let field = $state<HTMLTextAreaElement | null>(null);

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
  <p class="dialog-text">
    This text is added after the opening line of every process briefing. Changes apply when a process next
    joins or resumes.
  </p>
  <form class="line-form" onsubmit={save}>
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
