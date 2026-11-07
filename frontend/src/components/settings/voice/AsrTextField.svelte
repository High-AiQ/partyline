<script lang="ts">
  /** One text field of the recognizer form: label, input, and a hint that turns into the error. */
  interface Props {
    id: string;
    label: string;
    hint: string;
    value?: string;
    placeholder?: string;
    error?: string | undefined;
    disabled?: boolean;
  }

  let { id, label, hint, value = $bindable(""), placeholder = "", error, disabled = false }: Props = $props();
</script>

<div class="flex min-w-0 flex-col gap-1">
  <label for={id} class="text-[11px] text-cream-dim">{label}</label>
  <input
    {id}
    class="w-full rounded border bg-ink-3 px-2.5 py-1.5 text-[12.5px] text-cream {error
      ? 'border-red'
      : 'border-line'}"
    bind:value
    {placeholder}
    autocomplete="off"
    spellcheck="false"
    {disabled}
    aria-invalid={Boolean(error)}
    aria-describedby="{id}-hint"
  />
  <p id="{id}-hint" class="text-[10.5px] {error ? 'text-red' : 'text-cream-faint'}">{error ?? hint}</p>
</div>
