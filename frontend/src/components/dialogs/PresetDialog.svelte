<script lang="ts">
  /** Save what is currently in the attach form as a reusable preset. */
  import Modal from "../Modal.svelte";
  import PresetCard from "./PresetCard.svelte";
  import type { PresetDraft } from "../../lib/api";

  interface Props {
    preset: PresetDraft;
    close: () => void;
  }

  let { preset, close }: Props = $props();
</script>

<Modal title="save as preset" {close}>
  <PresetCard {preset} onsaved={close} />
</Modal>
