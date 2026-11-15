<script lang="ts">
  export interface LineOption {
    id: string;
    name: string;
  }
  interface Props {
    label: string;
    options: LineOption[];
    selected: string[];
    disabled?: boolean;
    onchange: (selected: string[]) => void;
  }
  let { label, options, selected, disabled = false, onchange }: Props = $props();
  const uid = $props.id();
  let open = $state(false);
  let query = $state("");
  let active = $state(0);
  const filtered = $derived(
    options.filter((option) => option.name.toLowerCase().includes(query.toLowerCase())),
  );
  const current = $derived(filtered[Math.min(active, filtered.length - 1)]);
  function toggle(id: string): void {
    if (disabled) return;
    onchange(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id]);
  }
  function keydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      open = false;
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active = open
        ? (active + (event.key === "ArrowDown" ? 1 : -1) + filtered.length) % Math.max(1, filtered.length)
        : 0;
      open = true;
    } else if (event.key === "Enter" || (event.key === " " && open && !query)) {
      event.preventDefault();
      if (open && current) toggle(current.id);
      open = true;
    } else if (event.key === "Backspace" && !query && selected.length) {
      onchange(selected.slice(0, -1));
    }
  }
</script>

<div
  class="relative min-w-0"
  onfocusout={(event) => {
    if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget))
      open = false;
  }}
>
  <label class="mb-1 block text-sm" for={uid}>{label}</label>
  <div
    class="flex flex-wrap items-center gap-1 rounded border border-line bg-ink-2 p-2 focus-within:border-copper"
  >
    {#each selected as id (id)}
      <button
        type="button"
        class="max-w-full rounded border border-line px-2 py-1 text-xs text-cream"
        {disabled}
        aria-label={`Remove ${options.find((option) => option.id === id)?.name ?? id}`}
        onclick={() => {
          toggle(id);
        }}
      >
        {options.find((option) => option.id === id)?.name ?? id} <span aria-hidden="true">×</span>
      </button>
    {/each}
    <input
      id={uid}
      role="combobox"
      aria-expanded={open}
      aria-controls={`${uid}-options`}
      aria-autocomplete="list"
      aria-activedescendant={open && current ? `${uid}-${current.id}` : undefined}
      class="min-w-24 flex-1 border-0 bg-transparent p-1 text-sm"
      placeholder="Filter lines…"
      {disabled}
      bind:value={query}
      oninput={() => {
        open = true;
        active = 0;
      }}
      onfocus={() => {
        open = true;
      }}
      onclick={() => {
        open = true;
      }}
      onkeydown={keydown}
    />
  </div>
  {#if open}
    <ul
      id={`${uid}-options`}
      role="listbox"
      aria-label={label}
      aria-multiselectable="true"
      class="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded border border-line bg-ink-2 p-1 shadow-lg"
    >
      {#each filtered as option, index (option.id)}
        <li
          id={`${uid}-${option.id}`}
          role="option"
          tabindex="-1"
          onkeydown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              toggle(option.id);
            }
          }}
          aria-selected={selected.includes(option.id)}
          class="flex cursor-pointer items-center gap-2 rounded px-2 py-2 text-sm text-cream hover:bg-ink-3"
          class:bg-ink-3={index === active}
          onmousedown={(event) => {
            event.preventDefault();
          }}
          onclick={() => {
            toggle(option.id);
          }}
        >
          <span
            aria-hidden="true"
            class="flex size-4 flex-none items-center justify-center rounded border border-cream-faint text-green"
            >{selected.includes(option.id) ? "✓" : ""}</span
          >
          <span class="min-w-0 break-words">{option.name}</span>
        </li>
      {:else}
        <li role="presentation" class="p-2 text-sm text-cream-faint">No matching lines</li>
      {/each}
    </ul>
  {/if}
</div>
