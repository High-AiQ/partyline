<script lang="ts">
  interface Props {
    id: string;
    label: string;
    value?: string;
    onchange: () => void;
  }

  const choices = ["A", "B", "C"];
  let { id, label, value = $bindable(""), onchange }: Props = $props();
</script>

<select {id} data-event-label={label} bind:value {onchange}>
  <option value="">Choose…</option>
  {#each choices as choice (choice)}
    <option value={choice}>{choice}</option>
  {/each}
</select>
