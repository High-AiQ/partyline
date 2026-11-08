<script lang="ts">
  import { tick } from "svelte";
  import { room } from "../../state/room.svelte.js";
  import { screenStatus } from "../../state/screen-status.svelte.js";
  import { tooltip } from "../../lib/tooltip";
  import ComposerBubble from "./ComposerBubble.svelte";

  let { error, online, onbegin }: { error: string; online: boolean; onbegin: () => void } = $props();
  let open = $state(false);
  let anchor: HTMLButtonElement;
  let container: HTMLDivElement;
  let menu = $state<HTMLDivElement | null>(null);
  const blocked = $derived(Boolean(room.screenShare && room.screenShare.status !== "declined"));
  const reason = $derived(
    blocked
      ? "Stop the live share before recording a walkthrough"
      : !online
        ? "Connect a computer to record a walkthrough"
        : "",
  );
  const label = "Screen: share live or record a walkthrough";

  function close(): void {
    open = false;
    anchor.focus();
  }
  async function show(): Promise<void> {
    open = true;
    await tick();
    menu?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }
  function keydown(event: KeyboardEvent): void {
    if (!open) {
      if (document.activeElement === anchor && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault();
        void show();
      }
      return;
    }
    if (event.key === "Tab") {
      open = false;
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const items = [...(menu?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])];
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      items[(index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
    }
  }
</script>

<svelte:window
  onkeydown={keydown}
  onpointerdown={(event: PointerEvent) => {
    if (open && event.target instanceof Node && !container.contains(event.target)) close();
  }}
/>
<div class="relative flex flex-none" bind:this={container}>
  <button
    bind:this={anchor}
    type="button"
    class="screen-menu grid size-11 flex-none place-items-center p-0"
    aria-label={label}
    aria-haspopup="menu"
    aria-expanded={open}
    use:tooltip={{ label }}
    onclick={() => {
      if (open) close();
      else void show();
    }}
  >
    <svg
      class="size-[18px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
      <circle cx="12" cy="10" r="2.5" class="fill-current stroke-none" />
    </svg>
  </button>
  {#if open}
    <div
      bind:this={menu}
      role="menu"
      aria-label="Screen"
      class="absolute bottom-full left-0 z-60 mb-1 flex min-w-max flex-col rounded-md border border-panel-line bg-panel p-1"
    >
      <button
        type="button"
        role="menuitem"
        class="border-0 bg-transparent p-2 text-left hover:bg-copper hover:text-ink focus-visible:bg-copper focus-visible:text-ink"
        onclick={() => {
          close();
          screenStatus.openPicker++;
        }}>Share live…</button
      >
      <button
        type="button"
        role="menuitem"
        aria-disabled={Boolean(reason)}
        use:tooltip={{ label: reason }}
        class="border-0 bg-transparent p-2 text-left aria-disabled:opacity-45 {reason
          ? ''
          : 'hover:bg-copper hover:text-ink'} focus-visible:bg-copper focus-visible:text-ink"
        onclick={() => {
          if (!reason) {
            close();
            onbegin();
          }
        }}>Record a walkthrough</button
      >
    </div>
  {/if}
  {#if error}<ComposerBubble><span role="alert" class="text-red">{error}</span></ComposerBubble>{/if}
</div>
