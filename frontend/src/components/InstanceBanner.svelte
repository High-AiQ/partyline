<script lang="ts">
  let { name }: { name: string } = $props();
</script>

<div
  class="instance-banner flex min-h-[25px] flex-none items-center justify-center gap-2 border-b px-3 py-[3px] font-mono text-[10px] leading-[1.2] tracking-[0.08em] text-copper uppercase border-[rgb(190_123_74/0.36)] bg-[rgb(190_123_74/0.08)]"
  role="status"
  aria-label={`Partyline instance: ${name}`}
>
  <span class="text-cream-faint" aria-hidden="true">instance</span>
  <strong class="truncate font-semibold">{name}</strong>
</div>
