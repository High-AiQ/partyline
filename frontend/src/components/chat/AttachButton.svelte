<script lang="ts">
  /** The desktop row's attach control; on a phone the composer menu carries the same action. */
  import { tooltip } from "../../lib/tooltip";
  import ComposerIcon from "./ComposerIcon.svelte";

  let { disabled, onclick }: { disabled: boolean; onclick: () => void } = $props();
</script>

<button
  class="attach grid size-11 flex-none place-items-center p-0 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
  type="button"
  aria-label="attach files"
  use:tooltip={{ label: "attach up to 6 files" }}
  {disabled}
  {onclick}
>
  <ComposerIcon name="attach" />
</button>
