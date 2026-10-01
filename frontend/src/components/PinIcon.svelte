<script lang="ts">
  interface Props {
    pinned: boolean;
    class?: string;
  }

  let { pinned, class: className = "size-[14px]" }: Props = $props();
</script>

<svg
  class={className}
  viewBox="0 0 24 24"
  fill={pinned ? "currentColor" : "none"}
  stroke="currentColor"
  stroke-width="1.8"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d="M16 9V4l1-1V2H7v1l1 1v5c0 1.66-1.34 3-3 3v2h5.97v7h2v-7H19v-2c-1.66 0-3-1.34-3-3z" />
</svg>
