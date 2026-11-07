<script lang="ts">
  /**
   * A small input-level bar for a live mic, with the mic's name as its tooltip
   * (and as text when `named`). The silence hint is the caller's to place.
   */
  let {
    level,
    label = null,
    named = false,
    wide = false,
  }: { level: number; label?: string | null; named?: boolean; wide?: boolean } = $props();
  const percent = $derived(Math.round(Math.max(0, Math.min(1, level)) * 100));
  const title = $derived(label ? `Mic: ${label}` : "Microphone level");
</script>

<span class="inline-flex min-w-0 items-center gap-1.5" {title}>
  <span
    class="mic-level-track block h-1.5 flex-none overflow-hidden rounded-full bg-line {wide
      ? 'w-24'
      : 'w-10'}"
    role="meter"
    aria-label="microphone level"
    aria-valuemin={0}
    aria-valuemax={100}
    aria-valuenow={percent}
  >
    <span class="mic-level-fill block h-full rounded-full bg-red-500" style:width="{percent}%"></span>
  </span>
  {#if named && label}<span class="truncate text-[10.5px] text-cream-faint">Mic: {label}</span>{/if}
</span>
