<script>
  /** Save what is currently in the attach form as a reusable preset. */
  import Modal from "../Modal.svelte";
  import PresetCard from "./PresetCard.svelte";

  let { preset, close } = $props();
</script>

<Modal title="save as preset" {close}>
  <PresetCard {preset} onsaved={close} />
</Modal>
