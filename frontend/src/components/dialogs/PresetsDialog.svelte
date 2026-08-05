<script lang="ts">
  /** Every saved preset, editable. */
  import Modal from "../Modal.svelte";
  import PresetCard from "./PresetCard.svelte";
  import { session } from "../../state/session.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();
</script>

<Modal title="presets" {close}>
  {#if !session.presets.length}
    <div class="dialog-note">no presets yet — fill the attach form and hit save</div>
  {:else}
    {#each session.presets as preset (preset.id)}
      <PresetCard {preset} />
    {/each}
  {/if}
</Modal>
