<script lang="ts">
  /** Confirm clearing one storage category: what goes, and how much space it frees. */
  import Modal from "../Modal.svelte";
  import ConfirmForm from "./ConfirmForm.svelte";
  import { humanSize } from "../../lib/files";
  import { storageApi, type StorageCategory } from "../../lib/storage-api";
  import { room } from "../../state/room.svelte";

  interface Props {
    category: StorageCategory;
    cleared: () => void;
    close: () => void;
  }

  let { category, cleared, close }: Props = $props();

  async function clearNow(): Promise<void> {
    const result = await storageApi.clear(category.key, room.conversation?.id ?? null);
    close();
    room.showNotice(
      `cleared ${category.label.toLowerCase()}: ${String(result.removed.length)} removed, ${humanSize(result.freed_bytes)} freed` +
        (result.skipped.length > 0 ? `, ${String(result.skipped.length)} kept` : ""),
    );
    cleared();
  }
</script>

<Modal title={`clear ${category.label.toLowerCase()}`} {close}>
  <p class="dialog-text">
    Removes {category.clearable_count} item{category.clearable_count === 1 ? "" : "s"}, about
    {humanSize(category.clearable_bytes)}{category.approximate ? " (approximate)" : ""}. Everything is
    re-checked when you confirm; data a running process, an in-review task or a saved restart plan still uses
    is kept.
  </p>
  <ul class="max-h-36 overflow-y-auto rounded border border-line bg-ink-3 p-2 text-[12px] text-cream-dim">
    {#each category.candidates as path (path)}
      <li class="truncate py-0.5">{path}</li>
    {/each}
    {#if category.clearable_count > category.candidates.length}
      <li class="py-0.5">and {category.clearable_count - category.candidates.length} more</li>
    {/if}
  </ul>
  <ConfirmForm
    phrase={null}
    prompt=""
    label="clear"
    busyLabel="clearing…"
    onconfirm={clearNow}
    oncancel={close}
  />
</Modal>
