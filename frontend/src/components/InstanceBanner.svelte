<script lang="ts">
  let { name }: { name: string } = $props();
</script>

<div class="instance-banner" role="status" aria-label={`Partyline instance: ${name}`}>
  <span aria-hidden="true">instance</span>
  <strong>{name}</strong>
</div>

<style>
  .instance-banner {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 25px;
    padding: 3px 12px;
    border-bottom: 1px solid rgb(190 123 74 / 0.36);
    background: rgb(190 123 74 / 0.08);
    color: var(--color-copper);
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.08em;
    line-height: 1.2;
    text-transform: uppercase;
  }

  .instance-banner span {
    color: var(--color-cream-faint);
  }

  .instance-banner strong {
    overflow: hidden;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
